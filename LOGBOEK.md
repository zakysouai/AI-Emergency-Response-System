# Logboek

Wat we gemaakt hebben, welke keuzes we maakten en waarom. Per stap aangevuld.
LLM: Claude (Claude Code, desktop-app). De code wordt door de student zelf gecommit.

## Werkafspraken
- Per stap maximaal ~200 lijnen code, alleen relevante code ("geen slop").
- Eerst brainstormen en keuzes vastleggen, dan pas coderen.
- Tests apart, wanneer de student erom vraagt.

---

## 2026-11-08: Analyse van de opdracht

**Eerste relevante prompt** (exacte tekst, nodig voor het rapport):
> lees eerst de assignment van de taak en breek het helemaal in stukjes en componenten die we apart kunnen behandelen/maken

**Resultaat:** de opdracht is opgedeeld in componenten:
data-laag → Bayes (wegtoestand) + HMM (verkeer) → kost per weg → A* → allocatie (CSP) + simulatie → validator + statistieken → `run.py` → tests en rapport.

**Vaststellingen over de data:**
- Eén systeem voor alle scenario's, geen code per scenario. De scenario's zijn testdata met hetzelfde formaat.
- De scenario's verschillen sterk: 5/12/26 knopen. In Scenario 2 hebben maar 3 wegen verkeersdata. Scenario 3 heeft een tijdlijn tot 5000 s.
- De HMM-parameters verschillen per scenario, dus ze moeten per scenario geladen worden.
- Elke weg is minstens zo lang als de rechte lijn tussen zijn knopen. Daardoor is de A*-heuristiek (afstand / maximale snelheid) admissible.
- Elke vereiste capability bestaat bij minstens één responder.

---

## 2026-11-08: Data-laag (`emergency/data/`)

**Gemaakt:**
- `models.py`: enums (RoadStatus, Weather, ReportSource, TrafficLevel, ResponderType, Priority) en onveranderlijke dataklassen (Node, Road, Graph, Responder, Incident, RoadEvidence, RoadCPTs, HMMParams, Scenario).
- `loaders.py`: `load_scenario(map)`, die alle bestanden inleest en controleert.
- `tests/test_data.py`: 38 tests.

**Keuzes en waarom:**
| Keuze | Waarom |
|---|---|
| Wegen zijn gericht, met `(from, to)` als sleutel | N1→N2 en N2→N1 krijgen verschillende reports |
| Kapotte input → `DataError` met bestand en regel. Verdachte input → `scenario.warnings` | Fouten vroeg vangen, maar het systeem laten draaien bij geldige maar vreemde data (bv. een onhaalbare deadline) |
| Weer per weg. Verschillend weer binnen één weg = fout | De README zegt "weather is local to the reported road" |
| Beschikbaarheid wordt één getal, `available_from` | Available → 0, Busy → `time_until_available` |
| Verkeersobservaties gesorteerd op `observation_nr` | Exact de vorm die het forward-algoritme nodig heeft |
| Alleen de begintoestand, onveranderlijk | Veranderende toestand (positie, bezet tot) hoort bij de simulatie |
| Geen externe libraries | Eenvoudig te installeren en te verdedigen |

**Controle van de juistheid:**
- Een onafhankelijk script (andere manier van inlezen) vergeleek elk veld met de loader: 0 verschillen.
- Mutatietest: 10 bugs bewust ingebouwd. **4 werden niet door de tests gevangen**: het sorteren van incidenten en van verkeersobservaties (de bestanden zijn toevallig al gesorteerd), negatieve `time_required` en een lege capability. Er zijn 4 tests bijgekomen, en nu worden alle 10 gevangen.
- De richting van de CPT's is gecontroleerd: de rijen sommeren tot 1, dus de rij is de echte toestand, P(gemeld | echt). De citizen-tabel is symmetrisch, dus daar kan de data de richting niet bewijzen. Dat is een aanname.

**Fouten van de LLM die opgemerkt zijn:**
- Tests met foute aannames over de data: een weg N1→N4 die niet bestaat, en CSV-bestanden waarvan aangenomen werd dat ze op een newline eindigen.
- Een echte bug in de loader: een CSV-rij met te veel velden liet het programma crashen in plaats van een `DataError` te geven. Opgelost.
- De eerste testsuite leek volledig (alles groen), maar de mutatietest toonde gaten. Les: groene tests van dezelfde LLM die de code schreef, bewijzen weinig.

---

## 2026-11-09: Ontwerpkeuzes (brainstorm, geen code)

### Keuze 1: wegen zonder reports
- **Gekozen:** marginaliseren over het weer: P(S) = Σ_w P(w)·P(S|w) → 68,5% Open / 18% Congested / **13,5% Blocked**.
- **Waarom:** standaard Bayes voor een ontbrekende variabele. Geen extra aanname.
- **Alternatieven:** vast weer Clear/Rain/Storm (willekeurig), het weer van de dichtstbijzijnde weg (veronderstelt ruimtelijke samenhang), zeker Open (negeert de onzekerheid).
- **Later:** optie 5, het weer afleiden uit de reports (bv. het meest voorkomende weer), als robuustheidsvariant.
- **Inzicht:** de keuze verandert vooral hoe riskant een route lijkt, niet welke route gekozen wordt. Een route over 5 wegen zonder reports is maar 0,865⁵ ≈ 48% zeker open.

### Keuze 2: kost per weg onder onzekerheid
- Verduidelijking: deze keuze bepaalt het **prijskaartje** van elke weg. A* kiest daarna de route.
- **Gekozen:** drempel + voorwaardelijke verwachting. Onbruikbaar als P(Blocked) > τ = 0,5, anders `t · (P_O + 1,5·P_C) / (P_O + P_C)`. Per route rapporteren we ook de betrouwbaarheid Π(1 − P_B).
- **Waarom:** eenvoudig, en τ = 0,5 betekent iets duidelijks ("eerder dicht dan open"). Geen verzonnen strafgetal.
- **Afgewezen:** MAP (gooit de twijfel weg), verwachte kost met straf M (M is willekeurig), kansbeperking (te moeilijk), Monte Carlo als planner (te zwaar, wel nuttig als evaluatie), omrijden onderweg (Canadian Traveller, te moeilijk en niet simuleerbaar).
- **Later:** optie 4, een risicotoeslag λ·(−ln(1 − P_B)). Die telt op over een route tot −ln(betrouwbaarheid). Vergelijken met optie 3 via Monte Carlo.
- **Vraag van de student over UCS:** UCS of A* kiest de route, maar heeft eerst kosten nodig. A* met h = 0 is precies UCS. We gebruiken dat in de tests (zelfde kost, minder uitgebreide knopen). UCS met kost −ln(1 − P_B) geeft de betrouwbaarste route.

### Keuze 3: verkeer (HMM)
- **Gekozen:**
  - **filtering** (het forward-algoritme), want we willen de huidige toestand. Viterbi geeft een hele reeks en smoothing gaat over het verleden;
  - **statisch** tijdens de simulatie, omdat `observation_nr` geen tijdseenheid is;
  - wegen zonder observaties krijgen `initial`;
  - factoren Low 1,0 / Medium 1,2 / High 1,5, als verwachte waarde;
  - **vermenigvuldigen** met de statusfactor.
- **Waarom:**
  - alle factoren ≥ 1, anders is de A*-heuristiek niet admissible;
  - High = 1,5 sluit aan bij Congested;
  - vermenigvuldigen omdat storm en drukte als onafhankelijke oorzaken behandeld worden.
- **Alternatieven:** de stationaire verdeling voor wegen zonder data (veel pessimistischer: 26% High tegenover 10%), het maximum van beide factoren, of verkeer alleen op Open wegen.
- **Beperking:** dubbel tellen is mogelijk. Een burger die "Congested" meldt, ziet misschien gewoon druk verkeer.

### Keuze 4: deadlines
- **Gekozen:** optie C, twee fasen:
  - **fase 1:** een CSP met de deadline als harde constraint, om zoveel mogelijk deadlines te halen;
  - **fase 2:** de overgebleven incidenten krijgen alsnog een responder, ook al is die te laat.
  - **strikte prioriteitsvolgorde:** vergelijk het tupel (#Critical gehaald, #High, #Medium, #Low, −totale responstijd).
- **Waarom:** realistisch (je stuurt ook te laat nog hulp), zonder verzonnen strafgewichten, en de deadline blijft een echte constraint.
- **Afgewezen:** alleen hard (je laat slachtoffers achter, en "100% deadlines gehaald" wordt misleidend), zacht met strafpunten (willekeurige getallen).
- **Gevolgen:**
  - te laat = een waarschuwing in de validator, geen ongeldig plan;
  - responstijd = aankomst − timestamp (inclusief wachten);
  - onbehandelde incidenten tellen niet mee in het gemiddelde, maar wel als gemiste deadline;
  - "op tijd" gaat over de verwachte aankomst, niet de echte.

---

## 2026-11-09: Wereldmodel (`emergency/world/`)

**Gemaakt** (205 lijnen, nog zonder tests):
- `distributions.py`: `normalize` (de α) en `expected_value`.
- `bayes.py`: `status_prior` en `road_posterior`. Netwerk Weather → Status → 3 reports, exacte inferentie door enumeratie.
- `hmm.py`: `filter_traffic` (het forward-algoritme, met normaliseren in elke stap).
- `world.py`: `WorldParams`, `expected_travel_time`, `RoadBelief`, `WorldModel` (`cost`, `neighbors`, `route_reliability`) en `build_world`.

**Keuzes en waarom:**
- Het wereldmodel wordt één keer gebouwd, omdat alle reports en observaties gekend zijn op t=0.
- Alle parameters zitten in `WorldParams`, zodat gevoeligheidsanalyses later geen nieuwe code vragen.
- `WorldParams` weigert factoren < 1, omdat de A*-heuristiek dan niet meer admissible is.
- **Aanname:** `initial` = P(X₁), de toestand bij de eerste observatie. Er komt dus geen transitie vóór de eerste observatie, anders dan bij AIMA, waar je met een prior op X₀ begint.

**Snelle controle** (nog geen formele tests):
- De cijfers komen overeen met eerdere handberekeningen. N1→N2 (Scenario 1) geeft 1,4 / 45,9 / 52,7 en is onbruikbaar. H1→N1 kost 30,5 × 1,104 × 1,028 = 34,6 s.
- In geen enkel scenario ligt een kost onder de basistijd.

**Vondsten:**
- **Scenario 2 valt in twee helften uiteen**: {H1, N1, N3–N6} en {H2, N2, N7–N10}. De enige verbinding, N1↔N2, heeft 83% kans om dicht te zijn. Elk incident heeft nog een capabele responder in zijn eigen helft. Gevolgen: A* moet "onbereikbaar" aankunnen, de allocatie werkt per helft, en de uitkomst is gevoelig voor τ (bij τ = 0,9 is de brug open).
- Onbruikbare wegen: Scenario 1 N1→N2, N2→N4, H1↔N3. Scenario 2 N1↔N2. Scenario 3 N5↔N16.

**Beperkingen:**
- `route_reliability` neemt aan dat wegen onafhankelijk van elkaar dicht zijn. Bij een storm is dat onrealistisch.
- Wegen zonder verkeersdata krijgen allemaal dezelfde verdeling. In Scenario 2 is dat 90% van de wegen, dus de HMM heeft daar weinig invloed.

---

## 2026-11-09: Testsuite voor het wereldmodel (`tests/test_world.py`)

**Gemaakt:** 31 tests. In totaal slagen er nu 69 tests (38 data + 31 wereld).

**Aanpak en waarom:**
- De verwachte waarden staan als **uitgeschreven handberekening** in de test, met de getallen uit de JSON-bestanden. Bijvoorbeeld `normalize(status(0.6*0.02, 0.3*0.08, 0.1*0.90))`. Zo kan je elke test op papier narekenen, en de test hergebruikt de formule uit de code niet.
- Naast exacte waarden testen we ook **eigenschappen uit de theorie**. Die vangen fouten die je met één getal mist.

**Wat getest wordt:**
| Onderdeel | Tests |
|---|---|
| Bayes | prior met gekend weer = rij uit de CPT; gemarginaliseerde prior (0,685 / 0,18 / 0,135); één police-report met de hand; N1→N2 met drie reports met de hand; de volgorde van reports maakt niet uit; een extra report dat hetzelfde zegt verhoogt de zekerheid; slechter weer geeft een hogere P(Blocked); onmogelijke evidence geeft een fout; elke belief is een geldige verdeling (alle scenario's) |
| HMM | zonder observaties = `initial`; één en twee observaties met de hand; de geschiedenis telt (niet alleen de laatste observatie); 2000 observaties zonder underflow |
| Kost | zeker Open + Low = basistijd; de formule met de hand (1,25 × 1,25); de grens van de drempel (P_B = τ is bruikbaar, erboven niet); geen deling door nul bij τ = 1; parameters met factor < 1 of een ontbrekend verkeersniveau worden geweigerd; de kost ligt tussen de basistijd en 2,25 × de basistijd (alle scenario's); een weg zonder reports én zonder verkeersdata gebruikt beide standaarden |
| WorldModel | de onbruikbare wegen van Scenario 1; `neighbors` en `cost`; elke weg gebruikt zijn eigen data; `route_reliability` (leeg pad = 1, één weg = 0,865, onbestaande weg = fout); de brug in Scenario 2 hangt af van τ |

**Controle van de tests zelf (mutatietest):** 19 bugs ingebouwd in het wereldmodel, bv. de CPT omgekeerd lezen, geen transitiestap, `>=` in plaats van `>`, het maximum in plaats van het product, of `neighbors` die dichte wegen meeneemt.
- Eerste ronde: **18 van de 19 gevangen.** Gemist: `build_world` zou de verkeersdata van een weg kunnen negeren (dan krijgt elke weg `initial`), en geen test merkte dat.
- Er is een test bijgekomen die controleert dat elke weg zijn eigen reports en observaties gebruikt. Nu worden **19 van de 19** gevangen.
- De mutatiescripts staan (nog) niet in de repo, alleen in de scratchpad van de sessie.

**Wat de tests niet bewijzen:**
- Dat onze **ontwerpkeuzes** goed zijn (τ, factoren, `initial` = P(X₁)). De tests controleren alleen dat de code die keuzes correct uitvoert.
- Dat de CPT's realistisch zijn. We vertrouwen op de gegeven data.

---

## 2026-11-09: Review van data-laag, wereldmodel en tests

**Aanpak:** de code opnieuw nagelezen, en de loader bewust met verdachte input bestookt (lege id, te weinig velden, gat in de nummering, kleine letters). Daarna de data gecontroleerd op randgevallen: BOM, gaten in `observation_nr`, dubbele reports per bron.

**Gevonden en opgelost:**
| Probleem | Gevolg | Oplossing |
|---|---|---|
| Een lege `responder_id` of `incident_id` werd stil aanvaard | Een responder met id `""` in het plan | `DataError` + 2 tests |
| Een gat in `observation_nr` (1, 2, 4) werd stil aanvaard | De HMM behandelt 2 → 4 als één stap en slaat ongemerkt een transitie over | Waarschuwing in `scenario.warnings` + test. De data zelf heeft geen gaten (alles begint op 1 en is aaneengesloten) |
| Geen `.gitignore` | `__pycache__/` kon per ongeluk mee gecommit worden | `.gitignore` met `__pycache__/`, `*.pyc` en `.pytest_cache/` |
| `warnings=tuple(warnings)` werd in dezelfde aanroep gebouwd als de loaders die er nog aan toevoegen | Werkte alleen dankzij de volgorde van de argumenten. Fragiel | Eerst alles laden, daarna pas `Scenario(...)` bouwen |

**Gecontroleerd en in orde:** geen BOM in de bestanden, geen dubbele reports van dezelfde bron op één weg, een rij met te weinig velden wordt geweigerd, en kleine letters in `availability` worden geweigerd.

**Na de fixes:** 72 tests slagen. De mutatietests vangen nog altijd 10/10 (data) en 19/19 (wereld). De onafhankelijke vergelijking met de ruwe bestanden vindt 0 verschillen.

**Bewust niet aangepast (klein, vermelden als beperking):**
- Een lege node-id in `city_graph.json` wordt niet apart gecontroleerd.
- τ wordt niet gecontroleerd op 0 ≤ τ ≤ 1. Een negatieve τ maakt alle wegen onbruikbaar.
- Twee reports van dezelfde bron op één weg zouden als onafhankelijk bewijs tellen (komt niet voor in de data).
- De map `.idea/` en `main.py` zijn niet gecommit. Of ze in de repo moeten, is jouw keuze.

---

## Open punten / volgende stappen
- [x] Tests voor het wereldmodel (met de hand nagerekende gevallen).
- [ ] Stap 2: A* (met h = 0 als UCS), met het pad `[start]` als start = doel en `None` als het doel onbereikbaar is.
- [ ] Stap 3: allocatie + event-loop (eerst brainstormen).
- [ ] Stap 4: validator, statistieken en `run.py`.
- [ ] Stap 5: Monte Carlo-evaluatie en gevoeligheidsanalyse (τ, weer, stationaire verdeling).
- [ ] Later, als er tijd is: optie 4 (risicotoeslag) en optie 5 (weer afleiden).
- [ ] `main.py` (het PyCharm-voorbeeld) verwijderen zodra `run.py` er is.
