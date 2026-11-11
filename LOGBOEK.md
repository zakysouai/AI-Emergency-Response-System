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

## 2026-11-09: Brainstorm zoekalgoritme, A* of UCS (geen code)

**Aanleiding:** de opdracht eist alleen "Search" uit de cursus, geen specifiek algoritme. De LLM had A* voorgesteld zonder het te meten. We wilden een onderbouwde keuze.

**Theorie:**
- Beide zijn compleet en optimaal (eindige graaf, kosten > 0). A* met h = 0 is precies UCS.
- Onze heuristiek h(n) = euclidisch(n, doel) / max_speed is **consistent**, dus ook admissible. Elke weg kost minstens afstand/snelheid ≥ euclidisch/max_speed (alle factoren ≥ 1), en de driehoeksongelijkheid geldt. Door de consistentie is A* als graph search (zonder knopen te heropenen) optimaal.
- A* wint alleen als h dicht bij de echte kost ligt, en alleen bij één doel. Zonder doel (één-naar-allen) is er geen heuristiek mogelijk.

**Meting** (wegwerpscript, niet in de repo). Alle paren (startlocatie van een responder of een incident → locatie van een incident), met het aantal uitgebreide knopen:

| Scenario | Paren (onbereikbaar) | A* per paar | UCS per paar | UCS één-naar-allen per bron | h / echte kost (gem.) |
|---|---|---|---|---|---|
| S1 | 20 (0) | 66 | 70 | 25 | 0,32 |
| S2 | 80 (43) | 365 | 388 | 66 | 0,45 |
| S3 | 176 (0) | 2251 | 2454 | 442 | 0,15 |

**Bevindingen:**
- A* bespaart maar 6–8% ten opzichte van UCS. Elke route had dezelfde kost (gecontroleerd).
- De heuristiek is zwak omdat max_speed = 30 m/s, terwijl veel wegen 15 m/s zijn. Bovendien kunnen de status- en verkeersfactoren de kost tot ×2,25 verhogen. De geometrie zelf is in orde (euclidisch/afstand ≈ 0,8 per weg).
- In S2 is 54% van de paren onbereikbaar (de stad is in twee helften gesplitst). Daar moet A* net als UCS de hele bereikbare helft afzoeken voor het `None` kan geven.
- De allocatie heeft een volledige reistijdmatrix nodig, en de wereld is statisch (alle info is beschikbaar op t = 0). Eén UCS één-naar-allen per bron levert die matrix met 3 tot 5 keer minder uitgebreide knopen dan A* per paar.

**LLM-fout:** A* werd voorgesteld omdat het het "sterkste" zoekalgoritme is, zonder na te gaan wat de allocatie eigenlijk nodig heeft (alle paren) en hoe goed de heuristiek is.

**Overwogen opties:**
- **A. A\* per paar:** te verdedigen, maar de meting werkt ertegen.
- **B. Alleen UCS één-naar-allen:** precies wat de allocatie nodig heeft.
- **C. UCS + een optionele heuristiek:** 3 lijnen extra, alleen om de vergelijking te tonen.

**Beslissing: optie B, alleen UCS één-naar-allen.**
- **Waarom:** de reden is conceptueel. De allocatie heeft de reistijden tussen *alle* relevante locaties nodig, en een heuristiek vraagt één doel. A* zou in het plan nergens gebruikt worden. Code die het systeem niet gebruikt, is slop.
- **Kritische vraag van de student:** "Als A* met h = 0 gewoon UCS is, waarom hebben we A* dan nodig?" Het antwoord: functioneel niet.
- **Op de verdediging:** A* is overwogen en past niet bij een één-naar-allen-zoekopdracht. Als ondersteuning dienen de meetcijfers hierboven (6–8% winst per paar, 3 tot 5 keer duurder dan één-naar-allen).
- **Wanneer A\* wel zou winnen:** een groot stratenplan met losse routeaanvragen, of een dynamische wereld waarin je telkens één nieuwe route moet zoeken.

**Naam: UCS of Dijkstra?** Algoritmisch is het hetzelfde: UCS zonder doeltest berekent de kortste paden vanuit één bron (Dijkstra). AIMA noemt UCS ook zo. De verschillen zitten in de vorm:
- Klassieke Dijkstra zet alle knopen vooraf op ∞ in de wachtrij en verlaagt hun prioriteit (decrease-key).
- UCS voegt knopen pas toe als ze ontdekt worden. Verouderde items worden overgeslagen in plaats van aangepast, en het werkt ook op impliciete of oneindige grafen.

Onze implementatie werkt zoals UCS (lui toevoegen), maar zonder doeltest, en het resultaat is dat van Dijkstra. In het verslag: "UCS zonder doeltest (equivalent aan Dijkstra single-source)". UCS is de term uit de cursus, en de opdracht vraagt methodes uit de cursus.

**Opgeruimd door deze keuze:**
- `Graph.max_speed` is verwijderd. Het diende alleen voor de heuristiek.
- De commentaren en een testnaam die nog naar "A*-admissibility" verwezen, zijn aangepast.
- De regel "alle factoren ≥ 1" in `WorldParams` blijft, met een nieuwe reden: factoren vertragen alleen, een weg is nooit sneller dan zijn basistijd.
- `Graph.euclidean` blijft alleen nog als sanity check op de data (een weg is minstens zo lang als de rechte lijn).
- 72 tests slagen nog altijd.
- Oudere logboekregels die A* noemen, laten we staan als geschiedenis. Dat was de stand op dat moment.

---

## 2026-11-09: Zoeken (`emergency/search/`)

**Wat:** `ucs.py` (ongeveer 70 lijnen).
- `uniform_cost_search(world, source)` geeft een `ShortestPaths`.
- `ShortestPaths.time_to(node)` geeft de reistijd, of `None` als de knoop onbereikbaar is.
- `ShortestPaths.path_to(node)` geeft `[source, …, node]`, of `None`.
- `travel_table(world, sources)` doet één zoekopdracht per verschillende bron. De allocatie kan dan opzoeken: `table[a].time_to(b)`.

**Keuzes en waarom:**
| Keuze | Waarom |
|---|---|
| UCS zonder doeltest (= Dijkstra single-source) | De allocatie heeft alle paren nodig (keuze 5 / optie B) |
| Lui toevoegen aan de frontier; een knoop is definitief zodra hij eruit komt; verouderde kopieën overslaan | De UCS-werking uit de cursus. Correct omdat elke wegkost > 0 is (de loader eist afstand en snelheid > 0, en alle factoren zijn ≥ 1) |
| Een buur alleen toevoegen als hij nog niet definitief is | Voorkomt nutteloze items. Het oude item niet aanpassen (decrease-key) houdt de code eenvoudig |
| Ouder-pointers in plaats van volledige paden op te slaan | Een pad pas opbouwen als het gevraagd wordt. Minder geheugen, één bron van waarheid |
| Een onbereikbare knoop ontbreekt gewoon in `cost` | Geen kunstmatige ∞ in de uitvoer. `time_to` geeft `None` (nodig voor Scenario 2) |
| Gelijke kosten worden beslist op het knoop-id (via de tuple-vergelijking van `heapq`) | Deterministisch, dus elke run geeft hetzelfde plan |
| `KeyError` bij een onbekende bron | Een tikfout in een id mag niet stil een "onbereikbaar" geven |
| `travel_table` sorteert en ontdubbelt de bronnen | Een locatie die zowel start als incident is, wordt maar één keer gezocht |

**Gecontroleerd** (wegwerpscript, nog geen tests):
- Op alle 3 de scenario's en alle bronnen: 0 verschillen met een onafhankelijke Bellman-Ford-berekening (een ander algoritme, dat simpelweg alle wegen herhaald ontspant).
- Elk pad begint bij de bron, eindigt bij het doel, en de som van zijn wegkosten is de gerapporteerde tijd.
- S1 vanuit H1: N3 via de omweg `[H1, N4, N3]` (70,1 s), want H1→N3 is onbruikbaar.
- S2 vanuit N1: alleen de eigen helft {H1, N1, N3–N6} is bereikbaar, en `path_to("N2")` geeft `None`.
- 72 bestaande tests slagen nog.

**Beperking:** de route is optimaal voor de *verwachte* kost. Of de weg echt open is, weten we niet. Dat is het werk van de betrouwbaarheid Π(1 − P_B) en de Monte Carlo-evaluatie (stap 5).

---

## 2026-11-09: Testsuite voor het zoeken (`tests/test_search.py`)

**Wat:** 17 tests in twee groepen.

**1. Kleine zelfgemaakte werelden** (`toy_world`, waarin elke weg precies de opgegeven kost heeft). Elke test richt zich op één manier waarop UCS fout kan gaan:
| Test | Wat kan er fout gaan |
|---|---|
| A→B kost 10, A→C→B kost 3 → route via C | Een knoop al definitief maken bij de eerste ontdekking in plaats van bij het verlaten van de wachtrij |
| De bron kost 0, met pad `[bron]` | Het randgeval start = doel |
| Onbruikbare weg A→B → omweg via C | Een weg gebruiken die dicht is |
| Een geïsoleerde knoop en een eenrichtingsweg → ontbreken in het resultaat | Een kunstmatige ∞ of 0 in plaats van "onbereikbaar" |
| A→B kost 1, B→A kost 5 | Wegen als ongericht behandelen |
| Twee routes met dezelfde kost → altijd via B | Een niet-deterministisch plan |
| Onbekende bron → `KeyError` | Een stil "onbereikbaar" bij een tikfout |

**2. De echte scenario's:**
- **S1:** vanuit H1 met de hand: N3 via N4 (12,6 + 57,5 = 70,1 s), omdat H1→N3 dicht is; N2 direct (53,5), want dat is goedkoper dan via N4 (75,6).
- **S2:** de twee helften zijn exact elkaars onbereikbare deel. Met τ = 0,9 is de stad weer één geheel.
- **S3:** de omweg rond de dichte weg N5↔N16, in beide richtingen. Heen en terug kosten verschillend (eigen verkeersdata per richting), en alle 26 knopen blijven bereikbaar.
- **Alle scenario's, vanuit elke knoop:** gelijk aan een onafhankelijke Bellman-Ford. Elk pad is berijdbaar en zijn kosten tellen op tot de gerapporteerde tijd.
- **`travel_table`:** één zoekopdracht per verschillende bron, gesorteerd.

**Mutatietest** (wegwerpscript): 9 bugs bewust ingebouwd in `ucs.py`, en **9/9 opgemerkt**:
- geen verouderde kopieën overslaan;
- een FIFO-wachtrij (zoals BFS);
- alleen de kost van de laatste weg tellen;
- het pad niet omdraaien;
- een foute parent;
- 0 in plaats van `None` voor onbereikbaar;
- een ongesorteerde tabel;
- een max-heap;
- een omgekeerde tie-break.

**Bewust niet getest:** twee "mutaties" veranderen het gedrag niet en zijn dus niet te testen.
- De controle `if nxt not in cost` weglaten: dan komen er alleen meer verouderde kopieën in de wachtrij.
- De expliciete `KeyError` weglaten: `graph.outgoing` geeft die dan zelf, alleen met een minder duidelijke boodschap.

**Resultaat:** 89 tests slagen (41 data + 31 wereld + 17 zoeken).

---

## 2026-11-09: Ontwerpkeuzes allocatie (brainstorm, geen code)

**Vooraf geanalyseerd:** voor elk incident de snelste capabele responder, die meteen vertrekt **vanaf zijn startlocatie** en verder niets doet. *(Later rechtgezet: dit is géén echte bovengrens. Een responder die al bij een ander incident staat, kan dichterbij zijn. Zie "Waar gaan de deadlines verloren?")*

| | Met ons kostenmodel | Zonder verkeersfactor | Met basistijden |
|---|---|---|---|
| S1 | 0/7 onhaalbaar | 0/7 | 0/7 |
| S2 | 5/12 | 2/12 | 0/12 |
| S3 | 7/20 | 6/20 | 2/20 |

- **Fase 2 van keuze 4** (te laat toch iemand sturen) is dus cruciaal, geen randgeval.
- **Het percentage gehaalde deadlines hangt sterk af van ons kostenmodel.** Vooral de verkeersfactoren 1,2 / 1,5 tellen mee, en die zijn onze eigen aanname. Dat nemen we op in de gevoeligheidsanalyse (stap 5) en het verslag.
- **De problemen per event zijn klein:** maximaal 6 incidenten tegelijk (S2 op t = 0) en 1 tot 4 capabele responders per incident. Een volledige zoektocht is haalbaar.

### Keuze 6: welke responders in het domein
- **Gekozen: B**, ook bezette responders, met hun toestand "vrij om t, op locatie x". De aankomst = max(vrij-om, nu) + reistijd.
- **Waarom:** we kiezen op wie het eerst *aankomt*, niet wie het eerst *vrij* is. Er is geen wachtlijst en er zijn geen extra events nodig.
- **Voorbeeld (S1, t = 50):** alle responders zijn bezet. I6 (deadline 140) kan naar R2 (vrij om 63,5 → aankomst 142,1) of naar R4 (vrij om 88,6, maar dichterbij → aankomst 140,7). Optie A ("alleen vrije responders") zou R2 kiezen, omdat die eerst vrij is.
- **Afgewezen: A**, alleen vrije responders plus een wachtlijst. Dat beslist later en dus met meer informatie, maar kiest niet op aankomsttijd en vraagt meer code.
- **Nadeel van B:** je legt je vroeg vast. Dat is het onderwerp van keuze 7.

### Keuze 7: zijn toewijzingen definitief?
- **Gekozen: B**, herzienbaar tot vertrek. Het wordt gebouwd als A + een parameter `revise`:
  - **3a:** `revise=False`. Er wordt niets herzien (= A). Eerst dit bouwen en testen.
  - **3b:** `revise=True`. Bij elk event worden alle taken die nog niet vertrokken zijn teruggenomen en samen met de nieuwe incidenten opnieuw opgelost. Test: B is per event nooit slechter dan A.
  - `run.py` gebruikt B. In het verslag vergelijken we A en B.
- **Meting** (ruwe gulzige simulatie, niet de echte CSP): in alle 3 de scenario's helpt herzien maar één keer.
  - **S3, t = 1140:** I10 (High, N5, deadline 2600) zou bij A te laat zijn (aankomst 3021).
  - R8 heeft dan al de taak I8 (Critical, N4, deadline 3000), maar is nog niet vertrokken, en staat om 1642 toevallig op N5.
  - Bij B doet R8 eerst I10 (klaar om 1677) en dan I8 (aankomst 2349). Beide zijn op tijd.
- **Discussie:**
  - Eerste advies van de LLM: A, omdat de gemeten winst klein is en B complex.
  - Tegenargument van de student: B bevat A, en op grotere schaal of in een onbekend scenario komt herzien vaker voor.
  - Kritische nuance: B wint alleen als een responder **ketens** kan krijgen (meerdere taken in één oplossing). Zonder ketens geeft herzien precies het plan van A. B is dus geen "A plus extra checks", maar vraagt een andere CSP.
  - Ook: een volledige zoektocht over ketens schaalt zelf slecht. Op echt grote schaal is een grens of heuristiek nodig.
- **Gevolg voor keuze 8:** ketens = ja. Die helpen ook A al: bv. S2 op t = 0, waar één responder twee taken kan krijgen in de beste volgorde.
- **Risico van uithongering:** beperkt. Een taak wordt definitief zodra de responder vertrekt.

### Keuze 8: de CSP met ketens
**Per event (tijdstip *nu*):**
- **Te plannen:** de nieuwe incidenten, plus bij `revise=True` de taken die nog niet vertrokken zijn.
- **Vast:** de toestand van elke responder (vrij om, locatie), na wat al vertrokken is.
- **Oplossing:** per responder een reeks incidenten. Per taak: vertrek = max(vrij, nu), aankomst = vertrek + reistijd, daarna vrij om aankomst + `time_required` op die locatie.

**8a. Gekozen: één optimalisatie in plaats van twee fasen.**
- Elk incident krijgt een plek. Er wordt geoptimaliseerd op het tupel (#Critical op tijd, #High, #Medium, #Low, −totale responstijd).
- Dat is equivalent aan fase 1 + fase 2 van keuze 4, maar de late incidenten krijgen ook de beste plek in plaats van een gulzige.
- **Eerlijk:** formeel wordt de deadline een doel met strikte voorrang in plaats van een harde constraint. Het probleem is dus een **COP**. De harde constraints zijn capability, bereikbaarheid, één taak tegelijk en niet vóór de timestamp.
- Een incident zonder capabele, bereikbare responder blijft onbehandeld.

**8b. Gekozen: invoegen op elke plek.**
- Een waarde is "(responder R, plek k in zijn keten)". Volledig: elke volgorde ontstaat via precies één reeks invoegingen.
- **Afgewezen:** "achteraan toevoegen" (mist het S3-voorbeeld) en "sorteren op deadline" (EDD, niet optimaal omdat reistijden meetellen).

**8c. Gekozen: de zoektocht beheersbaar houden.**
- **Branch-and-bound:** snoeien als zelfs "alle resterende incidenten op tijd" niet beter is dan de beste oplossing tot nu toe.
- **Waarom die grens klopt:** een invoeging maakt de taken erna nooit vroeger. UCS geeft echte kortste afstanden, dus d(A,B) ≤ d(A,X) + d(X,B).
- **Variabelenvolgorde:** prioriteit, dan deadline, dan de minste opties (MRV-achtig).
- **Waardenvolgorde:** eerst de vroegste aankomst, zodat er snel een goede grens is.
- **Vangnet:** een maximum aantal knopen per event. Wordt dat bereikt, dan nemen we de beste oplossing tot dan toe, met een waarschuwing. Zo werkt het ook op een groot onbekend scenario.

### Keuze 9: afspraken voor de simulatie
De oorspronkelijke vraag ("backtracking of gulzig?") is beantwoord door 8c. Wat overblijft:
1. **Events = alleen de timestamps van incidenten.** Elk incident krijgt meteen een plek, dus er is geen wachtlijst.
2. **"Vertrokken" = vertrek ≤ *nu*.** Alleen die taken liggen vast bij `revise=True`.
3. **Na een taak blijft de responder op de plaats van het incident.** Er is geen terugrit.
4. **Een responder die bij de start *Busy* is**, is vrij om `time_until_available`, op zijn startlocatie.
5. **Simulatie met de verwachte reistijden, zonder toeval.** De echte afloop testen we in stap 5 (Monte Carlo).

**Gevolgen:**
- De `time` in `plan.json` is het vertrektijdstip. Dat kan later zijn dan de timestamp.
- Een incident zonder capabele, bereikbare responder blijft onbehandeld.

**Optioneel, als er tijd is:** een gulzige baseline, om de winst van de CSP te tonen.

---

## 2026-11-09: Allocatie, stap 3a (`emergency/allocation/`)

**Wat:**
- **`csp.py`** (ongeveer 160 lijnen, inclusief docstrings): één event oplossen.
  - `schedule_chain` zet een keten om in `Assignment`s (vertrek, aankomst, klaar, pad).
  - `_chain_score` berekent de score van een keten zonder routes (die draait bij elke knoop).
  - `solve_event` is de backtracking met branch-and-bound.
- **`simulation.py`** (ongeveer 60 lijnen): de event-loop `simulate(scenario, world, revise=False)`. Die geeft `assignments`, `unhandled` en `warnings`.

**Keuzes tijdens het bouwen:**
| Keuze | Waarom |
|---|---|
| **#behandeld** toegevoegd aan het tupel, tussen #Low en −responstijd | De zoektocht heeft "onbehandeld laten" als laatste redmiddel nodig (bv. een onbereikbaar incident). Zonder deze component zou de optimalisatie te late incidenten liever onbehandeld laten, want dat verlaagt de totale responstijd |
| De score is optelbaar per keten: (aantal per prioriteit, #behandeld, −responstijd) | De totale score is de som van de ketens. Bij een invoeging hoeft alleen de keten van die responder herberekend te worden |
| Grens = huidige score + "alle resterende op tijd en behandeld, zonder vertraging" | Geldig omdat een invoeging de latere taken nooit vroeger maakt (driehoeksongelijkheid) |
| Snoeien bij ≤ (niet alleen <) | Bij een gelijke score blijft de eerst gevonden oplossing staan. Dat is deterministisch en snoeit meer |
| Volgorde van de variabelen ligt vast vooraf (prioriteit, deadline, minste opties) | Eenvoudiger dan dynamische MRV. De problemen zijn klein |
| `_legs` als gedeelde basis voor de score en voor de toewijzingen | Eén plek waar de tijdsregel staat: vertrek = max(vrij, nu), aankomst = vertrek + reis, vrij = aankomst + `time_required` |
| Onbehandelde incidenten worden later niet opnieuw geprobeerd | De wereld is statisch. In de 3 scenario's komt het niet voor |

**Gecontroleerd** (wegwerpscript, nog geen tests):
| | Toewijzingen | Onbehandeld | Op tijd | Max. aantal knopen per event | Tijd |
|---|---|---|---|---|---|
| S1 | 7 | 0 | 5/7 | 14 | < 1 ms |
| S2 | 12 | 0 | 7/12 | 37 | 1 ms |
| S3 | 20 | 0 | 10/20 | 175 | 2 ms |

- **Elk event, in elk scenario:** dezelfde score als een brute-force-oplossing (alle combinaties van responders en alle volgordes per responder). Er waren 0 verschillen.
- **S1:** R2 → I4 en R4 → I1, zoals voorspeld in de brainstorm. Beide Critical deadlines worden gehaald. I6 is te laat (140,7 tegenover 140), net als in het voorbeeld van keuze 6.
- **S2:** 7/12. Dat blijkt ook het maximum met alwetendheid (zie verder). De oorspronkelijke redenering ("5 zijn onhaalbaar") was wel fout.
- **S3:** 10/20. ~~Het maximum is 13~~ **Fout:** met alwetendheid zijn er 14 haalbaar (zie verder).
- Het maximum aantal knopen (100.000) wordt nergens bereikt. Het grootste event heeft 175 knopen nodig.

**Eerlijk:** `revise=True` zat er in 3 lijnen al bij, omdat het enige verschil is welke taken worden teruggenomen. Een eerste run geeft S3: 11/20 op tijd (tegenover 10) en een gemiddelde responstijd van 1327 s (tegenover 1431). Dat is waarschijnlijk het I10-geval uit keuze 7. Dit is nog **niet getest**: dat is stap 3b.

---

## 2026-11-09: Analyse "waar gaan de deadlines verloren?" (geen code in de repo)

**Aanleiding:** de student vond het percentage op tijd te laag ("ons model is niet goed genoeg").

**Methode** (wegwerpscript): elk scenario draaien met drie kostenmodellen en drie planners.
- **Kostenmodellen:**
  - ons model;
  - zonder verkeersfactor;
  - met basistijden (alles open, geen verkeer).
- **Planners:**
  - online A;
  - online B;
  - **alwetend:** alle incidenten op t = 0 gekend, maar niemand vertrekt voor de timestamp van zijn incident. Dat is de theoretische bovengrens voor eender welk online algoritme.

| Op tijd | Ons model (A / B / alwetend) | Zonder verkeersfactor | Basistijden |
|---|---|---|---|
| S1 (/7) | 5 / 5 / 5 | 6 / 6 / 6 | 7 / 7 / 7 |
| S2 (/12) | 7 / 7 / 7 | 11 / 11 / 11 | 12 / 12 / 12 |
| S3 (/20) | 10 / 11 / 14 | 13 / 13 / 16 | 19 / 17 / 19 |

**Bevindingen:**
- **Het algoritme is niet het probleem.** In S1 en S2 is online gelijk aan alwetend: het beste wat er bestaat. In S3 kost online beslissen 3–4 deadlines. Dat is de prijs van het niet kennen van de toekomst, en dat is inherent.
- **Het kostenmodel bepaalt het percentage.** S2 gaat van 7 naar 11 als je alleen de verkeersfactor weglaat. Met basistijden is bijna alles haalbaar: S1 en S2 zelfs 100%. Dat doet vermoeden dat de deadlines ontworpen zijn rond de basistijden.
- **Maar het percentage is zelfreferentieel.** "Op tijd" wordt gemeten met de *verwachte* aankomst uit ons eigen model (keuze 4). Een optimistischer model scoort beter op papier, terwijl de echte wegen niet veranderen. Het model bijstellen om het cijfer te verhogen zou dus valsspelen zijn. Alleen een evaluatie tegen gesimuleerde "echte" wegtoestanden (Monte Carlo, stap 5) kan zeggen of een model beter is.
- **Rechtzetting:** de eerdere bovengrens ("7 onhaalbaar in S3, dus max. 13") was fout. Ze keek alleen naar responders vanaf hun startlocatie, terwijl een responder na een taak dichterbij kan staan. Alwetend zijn er in S3 14 haalbaar.
- **Belangrijk voor 3b:** in S3 met basistijden scoort B (17) **slechter** dan A (19). "B is per event minstens even goed" geldt dus niet voor de hele simulatie. Een beslissing die nu beter is, kan later een slechtere toestand geven. In 3b uitgezocht: het is kortzichtigheid, geen bug (zie "Allocatie, stap 3b").

---

## 2026-11-09: Testsuite voor de allocatie, stap 3a (`tests/test_allocation.py`)

**Wat:** 24 tests. `toy_world` is verplaatst naar `tests/helpers.py`, zodat de zoek- en de allocatietests dezelfde helper gebruiken.

**1. Tijdsregel van een keten:**
- met de hand: vrij om 3 → aankomst 13 → klaar 17 → aankomst 22;
- nooit vertrekken voor *nu*;
- precies op de deadline aankomen telt als op tijd (opdracht 3.2);
- een onbereikbare stap geeft `None`.

**2. De CSP op kleine werelden**, één regel per test:
| Test | Wat kan er fout gaan |
|---|---|
| Alleen een capabele responder wordt gebruikt | De capability niet controleren |
| Twee Critical-incidenten die alleen met de juiste verdeling beide op tijd zijn | Gulzig de snelste responder per incident kiezen |
| Critical wint van High als maar één van de twee op tijd kan; High wordt toch behandeld | Prioriteiten negeren, of te late incidenten laten vallen (fase 2) |
| High moet *voor* Critical in de keten om beide te halen | Alleen achteraan toevoegen |
| Een onhaalbaar incident komt na het haalbare | Een te laat incident dat een ander mee te laat maakt |
| Bij gelijke deadlines beslist de responstijd | De laatste component van het tupel vergeten |
| Geen capability of onbereikbaar → onbehandeld | Een crash, of een ongeldige toewijzing |
| Maximum aantal knopen = 1 → toch een volledig plan, `complete=False` | Het vangnet |

**3. De scenario's:**
- **Elk event in elk scenario:** dezelfde score als brute kracht (alle combinaties en alle volgordes).
- **S1 met de hand:** alle 7 toewijzingen, I4 om 53,5, I1 vertrekt om 10 (R4 bezet tot 10) en komt aan om 78,6, I6 om 140,7 (te laat), 5 op tijd.
- **Elke toewijzing in elk scenario is geldig:**
  - de responder heeft de capability;
  - één taak tegelijk, en niet vertrekken voor de timestamp;
  - het pad start waar de responder staat en eindigt bij het incident;
  - alleen bruikbare wegen, en de kosten tellen op tot de reistijd;
  - klaar = aankomst + `time_required`;
  - elk incident precies één keer behandeld of onbehandeld.
- **Geen kennis van de toekomst:** de incidenten na tijdstip t wegsnijden verandert geen enkele beslissing tot t.
- **Een onbehandeld incident** (een capability die niemand heeft) komt in `unhandled` en verandert de rest van het plan niet.
- **Deterministisch**, en een waarschuwing als het maximum aantal knopen bereikt wordt.

**Mutatietest** (wegwerpscript): 19 bugs bewust ingebouwd, **19/19 opgemerkt**. Eerst werd er één gemist: "onbehandelde incidenten verdwijnen uit het resultaat". De scenario's hebben geen onbehandelde incidenten, dus geen enkele test merkte het. Daarvoor is de test met de onmogelijke capability toegevoegd. De grens `<` in plaats van `<=` bij de deadline werd ook pas opgemerkt na een extra test.

**Bewust niet getest** (dit verandert het resultaat niet):
- snoeien met `<` in plaats van `<=`;
- een andere variabelenvolgorde.

Beide geven dezelfde score, alleen met meer zoekwerk.

**Resultaat:** 113 tests slagen (41 data + 31 wereld + 17 zoeken + 24 allocatie).

---

## 2026-11-09: Allocatie, stap 3b (`revise=True`)

**Code:** er moest niets bijkomen. De 3 lijnen voor `revise=True` zaten al in `simulation.py` (zie 3a). Deze stap is het **onderzoeken en testen** ervan.

**Onderzocht: waarom scoort B slechter dan A in S3 met basistijden (17 tegenover 19)?**
- A en B wijzen exact **dezelfde** responders toe aan dezelfde incidenten. Alleen de volgorde in de keten van R8 verschilt.
  - **A:** R8 doet I5, I8, dan I10, en staat daarna op **N5**.
  - **B:** op t = 1140 neemt B I8 terug en zet I10 ervoor (R8 staat er al, dus responstijd 0). R8 eindigt daardoor op **N4**.
- Op t = 4200 en 4500 verschijnen I16 (High) en I17 (Critical). Vanaf N4 komt R8 te laat (5242 > 5100 en 6315 > 6000). Vanaf N5 zou hij op tijd zijn.
- **Conclusie: kortzichtigheid, geen bug.** B optimaliseert de incidenten die het *nu* kent. Waar een responder na zijn keten eindigt, telt niet mee in de score, terwijl dat voor de toekomst wel uitmaakt. Per event is B nooit slechter (zie de test hieronder), maar over de hele simulatie wel mogelijk.
- **Met ons eigen kostenmodel wint B wel:** S3 11 tegenover 10 op tijd, het I10-geval uit keuze 7. In S1 en S2 doen A en B het even goed.
- **Mogelijke verbetering** (niet gedaan, vermelden in het verslag): de eindpositie van een responder meetellen. Bijvoorbeeld via dekking: hoe goed staan de responders verspreid voor toekomstige incidenten. Dat vraagt een voorspelling van waar incidenten komen, en die data hebben we niet.

**Tests** (10 erbij in `tests/test_allocation.py`, nu 34):
| Test | Wat |
|---|---|
| Een nieuw incident vóór een wachtende taak | Kleine wereld: R is bezet tot 10 en krijgt op t = 0 C1. Op t = 5 verschijnt H naast hem. A zet H achter C1 (aankomst 35, te laat). B zet H ervoor (11) en C1 erna (26, nog op tijd) |
| B is per event nooit slechter dan "de oude taken houden" | In elk scenario en bij elk event: de optie die A zou kiezen vanuit dezelfde toestand ligt in de zoekruimte van B, dus B scoort minstens even goed |
| Een vertrokken taak verandert nooit | De incidenten na t wegsnijden verandert geen enkele taak die al vertrokken is. Een responder onderweg wordt nooit teruggeroepen, en zijn taak hangt niet af van de toekomst |
| Elke toewijzing is geldig, ook met `revise=True` | De bestaande geldigheidstest, nu voor beide instellingen |

**Mutatietest:** 5 bugs in de `revise`-logica, **5/5 opgemerkt**:
- ook vertrokken taken terugnemen;
- teruggenomen taken verliezen;
- dubbele taken;
- een taak die precies *nu* vertrekt als wachtend behandelen;
- `revise` stil uitzetten.

**Resultaat:** 123 tests slagen.

---

## 2026-11-09: Ontwerpkeuzes stap 4: uitvoer, validator, run.py (brainstorm, geen code)

**Het probleem:** het systeem rekent correct, maar levert nog niet op wat de opdracht vraagt.
- `plan.json` (5.1);
- een validator met zelf bedachte controles, getest en met beperkingen (5.1);
- `statistics.txt` met definities en tijdseenheid (5.2);
- `run.py` + `README.md` (8.2).

**Vondst:** `Scenarios/README.md` zegt "*no fixed traffic multipliers are prescribed; define and justify*". Onze verkeersfactoren (keuze 3) zijn dus een verwachte eigen keuze.

### Keuze 10: wat controleert de validator? (strenge versie, aanvaard)
- **Aanleiding:** de student vond het eerste voorstel niet streng genoeg. Bij het nalezen vonden we echte gaten:
  - een bool of NaN als `time`;
  - een string als `path`;
  - een overgeslagen incident dat alleen een waarschuwing gaf;
  - een dubbelzinnige volgorde bij gelijke tijden.
- **Werkwijze:** de validator leest het echte `plan.json` en rekent per responder de tijdlijn zelf opnieuw uit, op basis van pad en wegkosten. Hij hergebruikt niets van de planner, meldt alle fouten met een code, en werkt met een tolerantie van 1e-6.
- **Fouten:**
  - **Structuur:** S1 geen lijst; S2 niet precies de 4 sleutels; S3 een verkeerd type (een bool, NaN, ∞, een negatieve tijd of een leeg pad).
  - **Verwijzingen:** R1 onbekende responder; R2 onbekend incident; R3 een incident meer dan één keer; R4 de capability ontbreekt.
  - **Route:** P1 een onbekende knoop; P2 een onbestaande weg; P3 een geblokkeerde weg (P_B > τ); P4 het pad eindigt niet bij het incident; P5 het pad start niet waar de responder staat.
  - **Tijd:** T1 vertrek voor de timestamp; T2 vertrek voor `time_until_available`; T3 vertrek voor het einde van de vorige taak; T4 een dubbelzinnige volgorde bij gelijke vertrektijden.
  - **Volledigheid:** C1 een incident ontbreekt, terwijl een capabele responder het kan bereiken.
- **Waarschuwingen:**
  - W1 deadline gemist;
  - W2 een incident ontbreekt en niemand kan het behandelen;
  - W3 de route is duurder dan de kortste;
  - W4 nodeloos wachten.
- **Grensgevallen:**
  - C1 is een fout: ons systeem belooft iedereen hulp;
  - W1 blijft een waarschuwing (keuze 4). Anders is elk plan in S2/S3 ongeldig;
  - W3/W4 blijven waarschuwingen: de opdracht vraagt "*suitable*", niet "*shortest*".
- **Beperkingen:**
  - hetzelfde wereldmodel als de planner (P3, W3);
  - de verwachte aankomst, niet de echte;
  - geen controle op optimaliteit;
  - toekomstkennis alleen ten dele (T1).

### Keuze 11: grensgevallen (aanvaard)
- Een weg gebruiken met P(Blocked) > τ is een **fout**. De opdracht zegt "*Blocked — the road cannot be used*", en τ is onze definitie van "blocked".
- Een duurdere route dan de kortste is een **waarschuwing**: geldig, maar suboptimaal.

### Keuze 12: `statistics.txt` (aanvaard)
- **Verplicht:**
  - behandeld = het aantal incidenten in het plan, ook de te late;
  - gebruikte responders = responders met minstens één taak;
  - gemiddelde responstijd = aankomst − timestamp, over de behandelde incidenten, in seconden;
  - % deadlines gehaald = gehaald / *alle* incidenten (onbehandeld telt als gemist).
- **Extra:**
  - deadlines per prioriteit;
  - de onbehandelde en te late incidenten;
  - het resultaat van de validator;
  - de instellingen (τ, `revise`);
  - een korte uitleg van de definities.
- Monte Carlo-cijfers komen pas in stap 5.

### Keuze 13: `run.py` (aanvaard)
- `python run.py [scenariomap]`. Zonder argument draait het Scenario1.
- Opties: `--out DIR` (standaard de huidige map), `--no-revise`, `--tau`.
- Waarschuwingen worden afgedrukt.
- Exitcode ≠ 0 bij kapotte data of een ongeldig plan.
- Alleen de standaardbibliotheek.

### Keuze 14: `plan.json` (aanvaard)
- Precies de 4 sleutels uit het voorbeeld. Een automatische checker kan struikelen over extra velden.
- `time` wordt niet afgerond (fractionele seconden zijn toegelaten).
- Gesorteerd op vertrektijd, dan op responder.
- Onbehandelde incidenten staan niet in het plan, wel in de statistieken.

**Opsplitsing:**
- **4a:** `plan.json` + validator, met tests.
- **4b:** statistieken + `run.py` + `README.md`, met tests. Dan wordt ook `main.py` verwijderd.

---

## 2026-11-09: Stap 4a: `plan.json` + validator (`emergency/plan/`)

**Wat:**
- **`plan_json.py`** (ongeveer 20 lijnen): `plan_entries` en `write_plan`. Precies de 4 sleutels, en `time` = het vertrek, niet afgerond.
- **`validator.py`** (ongeveer 190 lijnen, waarvan ongeveer 30 de docstring met alle codes):
  - `validate_plan(data, scenario, world)` en `validate_plan_text(text, ...)` geven een `ValidationReport` (fouten en waarschuwingen, elk met een code).

**Keuzes tijdens het bouwen:**
| Keuze | Waarom |
|---|---|
| De tijdlijn per responder wordt zelf opnieuw berekend (sorteren op vertrek, dan locatie en vrije tijd volgen), uit pad en wegkosten | Onafhankelijk van de planner, zodat een fout in de planner niet stil herhaald wordt |
| Na een niet-berijdbare route (P1/P2/P3) worden de latere tijdscontroles van die responder overgeslagen | De aankomst is dan onbekend. Anders komen er vervolgfouten die niets zeggen |
| **W4 precies gedefinieerd:** vertrek is later dan "vrij" **en** valt niet samen met een event (een timestamp ≥ die van het incident) | Bij `revise=True` kan een taak legitiem pas op een later event vertrekken. Een naïeve "vertrek > vrij" zou daar valse waarschuwingen geven |
| **C1 kijkt naar bereikbaarheid vanaf de startlocatie** | Dat is exact. Een latere locatie van een responder is zelf bereikbaar vanaf zijn start, dus wat vanaf de start onbereikbaar is, blijft overal onbereikbaar |
| **W3 gebruikt UCS uit `emergency/search`** | Dat is geen plannercode en het is apart getest. Het blijft een waarschuwing |

**Gecontroleerd:**
- Alle plannen (3 scenario's × A/B) zijn geldig.
- De enige waarschuwingen zijn W1, precies één per te laat incident. Er zijn geen valse W3/W4.

**Tests** (`tests/test_plan.py`, 39 tests):
- het formaat van `plan.json`;
- alle gegenereerde plannen zijn geldig;
- **25 beschadigingen** van een geldig S1-plan, elk met de **exacte verzameling** foutcodes die verwacht wordt. Bijvoorbeeld:
  - een dubbel incident geeft R3 + P5 + T4, want de kopie start waar het origineel eindigde, en op hetzelfde moment;
  - een weggelaten of misvormd item geeft ook C1, want het incident ontbreekt dan.
- de volgorde in het bestand maakt niet uit;
- ongeldige JSON;
- de vier waarschuwingen houden het plan geldig.

**Mutatietest:** 19 bugs in de validator, **19/19 opgemerkt**. Eerst werd er één gemist: "taken in bestandsvolgorde in plaats van tijdsvolgorde". Ons eigen plan staat al op tijd gesorteerd, dus geen test zag het verschil. Daarvoor is de test met een omgekeerd plan toegevoegd.

**Resultaat:** 162 tests slagen.

---

## 2026-11-09: Stap 4b: `statistics.txt`, `run.py`, `README.md`

**Wat:**
- **`emergency/plan/statistics.py`** (ongeveer 100 lijnen):
  - `compute_statistics(scenario, assignments)` geeft een `Statistics` met de 4 verplichte cijfers, deadlines per prioriteit, de te late incidenten en de onbehandelde incidenten;
  - `format_statistics(...)` maakt de tekst. Bovenaan staat precies het blok uit het voorbeeld van de opdracht (5.2), daaronder de extra's van keuze 12 en de definities.
- **`run.py`** (ongeveer 70 lijnen): `python run.py [SCENARIO] [--out DIR] [--no-revise] [--tau TAU]`.
  - Laadt het scenario, bouwt het wereldmodel, plant, schrijft `plan.json`, **leest het terug van schijf en valideert het**, en schrijft dan `statistics.txt`.
  - Exitcode 0 = geldig plan, 1 = ongeldig plan (`statistics.txt` wordt toch geschreven, met de fouten erin), 2 = kapotte data of foute argumenten.
- **`README.md`**: installatie, gebruik, uitvoer, exitcodes, structuur, tests.
- **`main.py`** (het PyCharm-voorbeeld) is verwijderd.

**Keuzes tijdens het bouwen:**
| Keuze | Waarom |
|---|---|
| De statistieken komen uit de toewijzingen van de planner; de validator controleert ze onafhankelijk | De W1-test van 4a bewijst al dat de validator precies dezelfde te late incidenten vindt |
| Onbehandeld = incidenten van het scenario die niet in het plan staan (niet de lijst van de planner) | Robuuster: zo telt alles wat in het plan ontbreekt, wat de oorzaak ook is |
| W1 staat niet nog eens bij de validatie-waarschuwingen | Ze staan al in de lijst "Late incidents"; anders staat alles dubbel |
| Een kale naam (`Scenario2`) betekent altijd `Scenarios/Scenario2` | **Gevonden bij het testen:** een oude uitvoermap `Scenario2` in de huidige map won eerst van de echte scenariomap, met een verwarrende foutmelding. Een pad (`Scenarios/Scenario2`, `./mijnmap`) werkt nog altijd |
| `--tau` moet tussen 0 en 1 liggen | Een kans; buiten [0, 1] betekent het niets |

**Gecontroleerd met de hand:**
- S1: 7 behandeld, 4 responders, 107,4 s, 71,4% (5/7). I6 en I7 te laat, zoals in 3a.
- S2: 12 behandeld, 8 responders, 39,1 s, 58,3% (7/12).
- S3: 20 behandeld, 8 responders, 1326,7 s, 55,0% (11/20); met `--no-revise` 50,0% (10/20).
  - De gemiddelde responstijd lijkt enorm, maar S3 werkt op een andere tijdschaal: deadlines tot 7500 s, I8 (timestamp 360) heeft bv. een deadline van 3000.
- `--tau 0` op S2: bijna elke weg is dan "geblokkeerd", 11 incidenten onbehandeld, 8,3%. Het plan is geldig (alleen W2), dus exitcode 0. Correct: niemand kan die incidenten bereiken.
- Een onbestaand scenario geeft exitcode 2; `--tau 2` geeft een gebruiksfout.
- `run.py` werkt ook vanuit een andere map.

**Tests:** zie de volgende sectie.

---

## 2026-11-09: Testsuite voor stap 4b (`tests/test_run.py`)

**Aanpak:**
- De statistieken worden getest op **met de hand gemaakte toewijzingen** voor de incidenten van S1, niet op de uitvoer van de planner. Zo test elke test precies één definitie van keuze 12, los van de planner.
- `run.py` wordt via `main([...])` opgeroepen, met de uitvoer in een tijdelijke map.

**Tests** (19):
- **Statistieken:**
  - een geval met de hand nagerekend: responstijd vanaf de timestamp (I5 komt pas op 50 binnen), I2 komt exact op de deadline aan en telt als gehaald;
  - onbehandeld telt als gemist (gedeeld door **alle** incidenten), maar telt niet mee in de responstijd en staat niet bij "te laat";
  - de grens van de deadline (60 gehaald, 60,001 niet);
  - deadlines per prioriteit, alleen voor prioriteiten die voorkomen;
  - niets behandeld: geen deling door nul, "n/a";
  - het echte S1-plan: 7 / 4 / 107,37 s / 5 op tijd, I6 en I7 te laat.
- **Tekst:**
  - de eerste 5 lijnen zijn letterlijk het blok uit het voorbeeld van de opdracht;
  - fouten van de validator staan erin, W1 niet dubbel.
- **`run.py`:**
  - schrijft een geldig plan + statistieken, standaard Scenario1;
  - de opties `--no-revise`, `--tau` en `--out` (de map wordt aangemaakt);
  - een kale naam wint van een lokale map met dezelfde naam (de fout uit 4b);
  - een pad naar een scenariomap werkt;
  - een onbestaand scenario geeft exitcode 2 en schrijft niets;
  - een foute `--tau` geeft een gebruiksfout;
  - een ongeldig plan geeft exitcode 1 (de planner wordt vervangen door een die één incident laat vallen), en `statistics.txt` bevat dan "INVALID" en C1.

**Mutatietest:** 21 bugs ingebouwd in `statistics.py` en `run.py`; 20 opgemerkt. De ene "gemiste" is een **equivalente mutant**: hij herschrijft de voorwaarde van de te late lijst zodat ze logisch hetzelfde is. Geen test kan dat opmerken. Echte score: **20/20**.

**Resultaat:** 181 tests slagen.

---

## 2026-11-11: Ontwerpkeuzes stap 5: Monte Carlo-evaluatie (brainstorm, geen code)

**Het probleem:** het percentage "op tijd" in `statistics.txt` is een **voorspelling van ons eigen model**, geen meting. Twee dingen worden niet getest:
1. **Blokkades:** de kost van een bruikbare weg is de verwachte reistijd *gegeven dat de weg niet geblokkeerd is*. Een weg met P_B = 0,45 telt als gewoon rijdbaar.
2. **Spreiding:** "op tijd" = verwachte aankomst ≤ deadline. Bij een kleine marge (I6 in S1: 140,7 tegenover 140) is het in werkelijkheid ongeveer een muntworp.

**Wat Monte Carlo níét kan:** bewijzen dat de kansen in de bestanden kloppen; er is geen grondwaarheid. Het meet wel hoe goed de **beslisregels** (verwachte waarde + τ, revise) werken als het model klopt, en hoe robuust het plan is als het model niet klopt.

### Keuze 15: waaruit trekken we de "echte" wereld? (A, aanvaard)
- Uit onze eigen posterior, per gerichte weg onafhankelijk: status uit P(Status | weer, rapporten), verkeer uit de gefilterde HMM-verdeling (één keer per steekproef, daarna statisch, zoals keuze 3).
- Onafhankelijk mag: volgens `Scenarios/README.md` is het weer lokaal per weg.
- **Beperking:** N1→N2 en N2→N1 worden onafhankelijk getrokken; in werkelijkheid hangen ze waarschijnlijk samen.
- Alternatief B (een ander waarheidsmodel) is gevoeligheidsanalyse: keuze 18.

### Keuze 16: wat als een route geblokkeerd blijkt? (B, aanvaard)
- **B, omrijden:** de responder ontdekt een blokkade pas aan het begin van die weg en zoekt daar met UCS een nieuwe route, in het verwachte wereldmodel zonder de blokkades die hij al kent. Geen route meer: het incident mislukt en hij blijft staan waar hij is.
- Verworpen: A (taak mislukt meteen) is te streng en meet alleen Π(1 − P_B); C (opnieuw toewijzen tijdens de simulatie) is te veel werk voor de resterende tijd.
- **Uitvoering:** vertrek = max(geplande vertrektijd, echt vrij). Nooit vroeger dan gepland, anders vertrekt hij voor het incident bekend is. Vertraging schuift door in de keten. Staat hij niet aan het begin van zijn volgende pad, dan zoekt hij een route vanaf zijn huidige plek.

### Keuze 17: reistijd van een weg in een steekproef (aanvaard)
- Open: `t × verkeersfactor`; Congested: `t × 1,5 × verkeersfactor`; Blocked: onbruikbaar.
- Dezelfde factoren als het model, zodat we het effect van spreiding en blokkades meten, niet van andere aannames.

### Keuze 18: cijfers en vergelijkingen (aanvaard)
- Per steekproef: % deadlines gehaald (over alle incidenten), gemiddelde responstijd, aantal niet bereikte incidenten. Samengevat: gemiddelde met 95%-betrouwbaarheidsinterval, en **P(op tijd) per incident**.
- N = 1000, vaste seed. **Common random numbers:** elke variant wordt op dezelfde getrokken werelden uitgevoerd.
- Vergelijkingen: (1) beslisparameters (τ ∈ {0,3; 0,5; 0,7; 0,9}, revise A/B) onder dezelfde waarheid; (2) een verkeerd model (stationaire verkeersverdeling, "Storm" voor wegen zonder rapporten) met hetzelfde plan.

### Keuze 19: waar komt het? (aanvaard)
- `emergency/evaluation/montecarlo.py`.
- `run.py --samples N` (standaard 1000, 0 = uit) voegt een sectie "Monte Carlo" toe aan `statistics.txt`, onder het verplichte blok.
- Gevoeligheidsanalyse in een apart script `evaluate.py`.

**Tijdsplanning (deadline 12/11 23:59):** 5a = trekken + uitvoeren + cijfers + sectie in `statistics.txt`; 5b = `evaluate.py`; daarna het verslag. **Laten vallen:** kostenmodel fijnregelen en optie 4/5. Die komen in het verslag als voorgestelde verbeteringen, met hoe we ze met Monte Carlo zouden beoordelen.

---

## 2026-11-11: Stap 5a: Monte Carlo (`emergency/evaluation/`)

**Wat:**
- **`montecarlo.py`** (ongeveer 160 lijnen, waarvan ongeveer 20 docstring):
  - `sample_worlds(truth, n, seed)`: N werelden; per gerichte weg een status en een verkeersniveau uit de verdelingen van het `truth`-wereldmodel. De werelden worden één keer getrokken en dan voor elk plan hergebruikt (common random numbers).
  - `execute(scenario, plan, world, sample)`: voert het vaste plan uit volgens keuze 16 en geeft de echte aankomsttijd per bereikt incident.
  - `evaluate(...)` geeft een `MonteCarloResult`: % gehaald per wereld, responstijd per wereld, aantal niet bereikte incidenten per wereld, P(op tijd) per incident. `mean_ci` geeft het gemiddelde en de halve breedte van het 95%-interval (normale benadering).
  - `format_monte_carlo(...)`: de sectie voor `statistics.txt`.
- **`run.py`**: `--samples N` (standaard 1000, 0 = uit) en `--seed S` (standaard 0).
- **README** bijgewerkt.

**Keuzes tijdens het bouwen:**
| Keuze | Waarom |
|---|---|
| Omrijden gebruikt UCS uit `emergency/search` op een kleine wrapper `_KnownWorld` (het verwachte wereldmodel zonder de gekende blokkades) | Geen wijziging aan de geteste zoekcode nodig; UCS heeft alleen `graph` en `neighbors` nodig |
| De `truth` voor het trekken is een apart wereldmodel | Zo kan 5b een ander waarheidsmodel (stationair verkeer, Storm) gebruiken met hetzelfde plan |
| Een responder onthoudt de blokkades die hij tegenkwam, ook voor zijn volgende taken | Realistisch, en het kost niets extra |
| Het rijden stopt altijd | Elke stap rijdt een weg verder of voegt een nieuwe gekende blokkade toe; beide zijn eindig |

**Controle van de uitvoering:** in een "wereld" zonder blokkades en met precies de verwachte reistijden geeft `execute` voor alle 3 scenario's × A/B **exact** de aankomsttijden van de planner (verschil ≤ 1e-12). Een andere seed (7) geeft voor S1 49,9% ± 1,4 tegenover 50,2% ± 1,4.

**Resultaten** (1000 werelden, seed 0, `revise` = B tenzij vermeld):
| | voorspeld (verwachte tijden) | Monte Carlo | niet bereikt per wereld | responstijd voorspeld → MC |
|---|---|---|---|---|
| S1 | 71,4% | 50,2% ± 1,4 | 0,88 | 107,4 → 109,5 s |
| S2 | 58,3% | 54,6% ± 1,0 | 0,10 | 39,1 → 41,7 s |
| S3 (A) | 50,0% | 39,5% ± 0,6 | 3,49 | 1430,5 → 1573,4 s |
| S3 (B) | 55,0% | 42,7% ± 0,6 | 3,40 | 1326,7 → 1497,1 s |

**Wat leren we hieruit:**
- **Het voorspelde percentage is te optimistisch**, in S1 met ruim 20 procentpunten. Dat bevestigt de vrees uit 3a: het eigen cijfer is zelfreferentieel.
- **De grootste oorzaak zijn blokkades**, niet de spreiding van de reistijd. In S1 wordt I3 in 297 van de 1000 werelden niet bereikt: zijn route is maar met kans 0,65 vrij (`route_reliability`), en S1 heeft amper omwegen. Het kostenmodel (reistijd *gegeven niet geblokkeerd*) negeert dat risico helemaal.
- **Waar komt die blokkadekans vandaan?** De meeste wegen hebben geen rapporten en krijgen P(Blocked) = 0,135, door te marginaliseren over het weer (keuze 1). Die aanname bepaalt de Monte Carlo-cijfers dus sterk. 5b test ze met de "Storm"-variant.
- **Het voordeel van B in S3 blijft overeind:** +3,2 procentpunten, ver buiten de intervallen. Dat is nu een *gemeten* voordeel, niet alleen een voorspeld.
- **Opgelet bij de responstijd in Monte Carlo:** die is het gemiddelde over de *bereikte* incidenten. Als moeilijke incidenten mislukken, vallen ze weg; het cijfer is dan te gunstig. Daarom staat "Incidents not reached" ernaast.
- **Gevolg voor het verslag:** dit is precies het argument voor optie 4 (risicotoeslag voor P_B). We kunnen het nu meten in plaats van beweren, maar we bouwen het niet meer (tijd).

**Tests:** zie de volgende sectie. Nog niet gedaan: 5b (`evaluate.py`).

---

## 2026-11-11: Testsuite voor stap 5a (`tests/test_montecarlo.py`)

**Aanpak:**
- **Trekken** wordt getest tegen de verdelingen waaruit getrokken wordt: met zekere beliefs (exacte reistijd) en statistisch op S1 (4000 werelden, afwijking < 4 standaardfouten).
- **Uitvoeren** wordt getest op een kleine stad (A, B, C, G) waarvan de echte reistijden per test met de hand gekozen worden. Zo is elke verwachte aankomsttijd op papier na te rekenen.

**Tests** (24):
- **Trekken:**
  - de reistijd per combinatie status × verkeer (4 gevallen) en een zekere blokkade;
  - de frequenties volgen de beliefs: P(Blocked) voor een weg met en zonder rapporten, en de volledige verdeling van de vertragingsfactor;
  - reproduceerbaar met dezelfde seed, anders met een andere.
- **Uitvoeren:**
  - het geplande pad met de echte tijden;
  - nooit vroeger vertrekken dan gepland;
  - vertraging schuift door naar de volgende taak;
  - omrijden pas aan het begin van de geblokkeerde weg;
  - de goedkoopste omweg *volgens het verwachte model*, en geen weg die het model onbruikbaar vindt (P_B > τ), ook al is die in werkelijkheid open;
  - twee blokkades na elkaar: het incident mislukt, de responder blijft staan en rijdt van daar naar zijn volgende taak;
  - in de verwachte wereld exact de aankomsttijden van de planner (3 scenario's × A/B).
- **Samenvatten:**
  - `evaluate` met de hand: 3 werelden (precies op de deadline, te laat, niet bereikt);
  - het betrouwbaarheidsinterval;
  - de tekst;
  - `run.py --samples`: de sectie staat er alleen als erom gevraagd wordt, en is reproduceerbaar.

**Fouten in de tests zelf (door de LLM, gevonden doordat de tests faalden):**
- Factor 1,5 als "High verkeer" geteld, terwijl Congested + Low ook 1,5 geeft. De test vergelijkt nu de volledige verdeling van de factor.
- De hulpfunctie voor een getrokken wereld kende de extra wegen van één test niet.

**Mutatietest:** 24 bugs in `montecarlo.py`. Eerst werden er 21 opgemerkt:
- **gemist:** deadline `<` in plaats van `<=` → de test met de hand laat nu één wereld precies op de deadline aankomen;
- **gemist:** omrijden zonder verwachte kosten en zonder τ → nieuwe test met twee omwegen en een "onbruikbare" weg;
- **equivalent:** de begintijd `available_from` negeren. In een geldig plan is de vertrektijd altijd ≥ `available_from` (validatorregel T2), dus `max(vertrek, vrij)` verandert niet.
- Twee mutanten laten het omrijden eeuwig lussen; de tijdslimiet vangt ze.
- Eindscore **23/24**, de overblijvende is equivalent.

**Resultaat:** 205 tests slagen.

---

## 2026-11-11: Stap 5b: gevoeligheidsanalyse (`evaluate.py`)

**Wat:** `evaluate.py` (ongeveer 110 lijnen, waarvan ongeveer 15 docstring) maakt per scenario één tabel. `python evaluate.py [SCENARIO ...] [--samples N] [--seed S] [--out FILE]`.
- **Beslisvarianten:** τ ∈ {0,3; 0,5; 0,7; 0,9} en zonder revise. Elk plan wordt in **dezelfde** getrokken werelden uitgevoerd als het basisplan. De kolom "vs base" is daarom een **gepaard verschil** per wereld, met een eigen 95%-interval. Dat is veel smaller dan de intervallen van de twee gemiddelden apart.
- **Waarheidsvarianten:** het basisplan in werelden uit een ander model voor de wegen *zonder data*: verkeer uit de stationaire verdeling van de HMM (π = π·T, met iteratie) in plaats van `initial`, of het weer "Storm" in plaats van de weersprior.
- Duurt ongeveer 2 s voor de 3 scenario's.

**Resultaten** (1000 werelden, seed 0, % deadlines gehaald):
| variant | S1 | S2 | S3 |
|---|---|---|---|
| basis (τ 0,5, revise), voorspeld | 71,4 | 58,3 | 55,0 |
| basis, Monte Carlo | 50,2 ± 1,4 | 54,6 ± 1,0 | 42,7 ± 0,6 |
| τ 0,3 (vs basis) | +0,0 | +0,0 | +0,0 |
| τ 0,7 en τ 0,9 (vs basis) | **+3,9 ± 0,8** | +0,0 | **−3,1 ± 0,2** |
| zonder revise (vs basis) | +0,0 | +0,0 | **−3,2 ± 0,2** |
| waarheid: stationair verkeer | 50,2 ± 1,4 | 45,5 ± 1,0 | 40,0 ± 0,6 |
| waarheid: Storm | **20,6 ± 0,8** | **36,9 ± 0,8** | **17,0 ± 0,5** |

**Controles en verklaringen:**
- **Waarom zijn veel τ-rijen gelijk?** P(Blocked) neemt maar een paar waarden aan: ≈0, 0,135 (alle wegen zonder rapporten), 0,527, 0,83 en 0,998. τ verandert het plan alleen als het over zo'n waarde springt. τ 0,3 ≡ τ 0,5, en τ 0,7 ≡ τ 0,9 in S1/S3. In S2 maakt τ 0,9 de wegen met 0,83 bruikbaar, maar het plan gebruikt ze niet.
- **Stationair verkeer verandert niets in S1:** daar hebben alle 14 wegen observaties, dus de variant raakt geen enkele weg. In S2 hebben maar 3 van de 30 wegen observaties: −9,1 procentpunten.
- **De stationaire verdeling** is in S1 en S3 Low 0,354 / Medium 0,386 / High 0,26, tegenover `initial` 0,6 / 0,3 / 0,1. In S2 (een andere HMM) is ze 0,288 / 0,423 / 0,288, tegenover 0,5 / 0,35 / 0,15. Ze is dus overal veel pessimistischer, zoals al vermoed in keuze 3. *(Verbeterd bij de tests van 5b: eerst stond hier één verdeling voor alle scenario's, maar elk scenario heeft een eigen HMM.)*

**Wat leren we hieruit (voor het verslag):**
1. **Er is geen beste τ.** In S1 helpt een hogere τ (+3,9), in S3 schaadt hij (−3,1). In S1 gebruikt τ 0,7 voor I2 de directe weg N1→N2 (P_B 0,527). Als die geblokkeerd is, ziet de responder dat al bij zijn vertrek in N1 en rijdt hij **zonder verlies** om via H1. Een riskante weg met een goedkope uitwijkmogelijkheid is dus een goede gok. Een drempel op P_B ziet dat verschil niet. **Voorgestelde verbetering:** een kost die de verwachte omrijtijd bij een blokkade meerekent (een verwachte kost "met herstel"), met optie 4 (risicotoeslag) als eenvoudige versie. Beoordelen met precies deze tabel.
   - **Opgelet:** dat resultaat hangt af van onze aanname dat een blokkade pas aan het begin van de weg ontdekt wordt (keuze 16).
2. **Revise helpt gemeten in S3** (+3,2 ± 0,2), en maakt in S1/S2 geen verschil (de plannen zijn daar gelijk, zie 3b).
3. **De grootste onzekerheid is de weersaanname voor wegen zonder rapporten (keuze 1).** Is het daar Storm, dan zakt S3 van 42,7% naar 17,0%, en worden er 12,2 incidenten per wereld niet bereikt. Geen enkele beslisparameter heeft zo'n groot effect. **Voorgestelde verbetering:** optie 5 (het weer afleiden uit de rapporten van naburige wegen), te beoordelen met de waarheidsvarianten.
4. **De responstijd daalt bij Storm in S1 (109,5 → 107,0 s).** Dat is geen verbetering: moeilijke incidenten mislukken en vallen weg uit het gemiddelde. Dat is precies de vertekening die in 5a al vermeld werd.

**Tests:** zie de volgende sectie.

---

## 2026-11-11: Testsuite voor stap 5b (`tests/test_evaluate.py`)

**Kleine wijziging in de code:** `truth_variant` weigert nu een onbekende variant (`ValueError`). Eerst gaf een tikfout stil de gewone wereld terug.

**Tests** (15):
- **Stationaire verdeling:**
  - met de hand: 2 toestanden, T = [[0,9; 0,1]; [0,5; 0,5]] geeft (5/6, 1/6);
  - voor alle 3 scenario's een vast punt (π·T = π, som 1);
  - de waarden van S1.
- **Waarheidsvarianten, weg per weg:** alleen de wegen zonder observaties krijgen π, alleen de wegen zonder rapporten krijgen de Storm-verdeling; de rest blijft onveranderd. Een onbekende variant wordt geweigerd.
- **`analyse`:**
  - de rijen in de juiste volgorde, de juiste voorspelde percentages;
  - **common random numbers:** in S2 verandert geen enkele beslisvariant het plan, dus elke rij moet *wereld per wereld* gelijk zijn aan de basis;
  - in S3 veranderen τ 0,7 en "zonder revise" het plan echt (voorspeld 50% tegenover 55%);
  - reproduceerbaar.
- **Tabel:** een gepaard verschil met de hand. De variant is per wereld precies 10 punten beter: +10,0 ± 0,0, terwijl het gemiddelde alleen een interval van ±56,6 heeft. Basis- en waarheidsrijen tonen geen verschil.
- **Commandolijn:** `--out` schrijft precies wat afgedrukt wordt; een selectie van scenario's; `--samples 1` is een gebruiksfout.

**Fouten in de tests zelf (door de LLM):**
- Verwachte waarden van de stationaire verdeling van S1 gebruikt voor S2. Elk scenario heeft een eigen HMM. Daardoor bleek ook een zin in "Stap 5b" fout; die is verbeterd.
- Een verkeerde kolomindex, omdat "tau 0.7" uit twee woorden bestaat.

**Mutatietest:** 15 bugs in `evaluate.py`. Eerst 13 opgemerkt. Gemist: "τ-variant genegeerd" en "revise-variant genegeerd". In S2 verandert geen enkele variant het plan, dus geen test zag het verschil. De nieuwe test op S3 vangt ze: **15/15**.

**Resultaat:** 220 tests slagen.

---

## Open punten / volgende stappen
- [x] Tests voor het wereldmodel (met de hand nagerekende gevallen).
- [x] Stap 2: UCS één-naar-allen per bron (keuze B).
- [x] Tests voor het zoeken (17 tests, mutaties 9/9 opgemerkt).
- [x] Brainstorm stap 3 (keuzes 6–9).
- [x] Stap 3a: CSP met ketens + event-loop, `revise=False`.
- [x] Tests voor 3a (24 tests, mutaties 19/19 opgemerkt).
- [x] Stap 3b: `revise=True` getest. B is per event nooit slechter, maar globaal soms wel (kortzichtigheid).
- [x] Stap 4a: `plan.json` + validator (39 tests, mutaties 19/19).
- [x] Stap 4b: statistieken + `run.py` + `README.md`.
- [x] Tests voor 4b (19 tests, mutaties 20/20).
- [x] Brainstorm stap 5 (keuzes 15–19).
- [x] Stap 5a: Monte Carlo in `statistics.txt`.
- [x] Tests voor 5a (24 tests, mutaties 23/24, de overblijvende is equivalent).
- [x] Stap 5b: `evaluate.py` (gevoeligheidsanalyse: τ, revise, stationaire verdeling, Storm).
- [x] Tests voor 5b (15 tests, mutaties 15/15).
- [ ] Verslag (3 pagina's + promptpagina).
- [ ] ~~Kostenmodel fijnregelen~~: laten vallen wegens tijd (keuze 19); komt in het verslag als voorgestelde verbetering, te beoordelen met Monte Carlo.
- [ ] Later, als er tijd is: optie 4 (risicotoeslag) en optie 5 (weer afleiden).
- [x] `main.py` (het PyCharm-voorbeeld) verwijderd.
