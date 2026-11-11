# Storm emergency response

AI decision support for emergency responders during a storm (AI practicum,
UAntwerpen). For one scenario the system decides which responder handles which
incident, along which route and when it leaves. It combines:

- **Bayesian reasoning**: the probability that a road is Open / Congested / Blocked,
  from the weather and the (unreliable) road reports;
- **an HMM**: the current traffic level per road, from the traffic observations;
- **search**: uniform-cost search over the expected travel times;
- **constraint-based allocation**: a branch-and-bound CSP that assigns incidents
  to responders, re-planned every time new incidents become known.

## Requirements

- Python 3.10 or newer. The system itself only uses the standard library.
- `pytest`, only to run the tests.

```bash
python3 -m pip install pytest
```

## Running

From the repository root:

```bash
python3 run.py Scenario2
```

This writes `plan.json` and `statistics.txt` to the current folder and prints
the statistics. Without an argument it runs `Scenario1`.

| Argument | Meaning |
|---|---|
| `SCENARIO` | the name of a folder in `Scenarios/` (default `Scenario1`), or a path to any scenario folder |
| `--out DIR` | folder for the output files (default: current folder) |
| `--no-revise` | never re-plan tasks that have not departed yet |
| `--tau TAU` | a road counts as blocked when P(Blocked) > TAU (default 0.5) |
| `--samples N` | Monte Carlo: execute the plan in N sampled true worlds (default 1000, 0 = off) |
| `--seed S` | seed of the Monte Carlo sampling (default 0) |

Exit code: `0` valid plan, `1` the written plan failed validation, `2` unusable
input (missing or malformed scenario files, bad arguments).

## Output

- **`plan.json`**: a list of assignments `{"responder_id", "incident_id", "path", "time"}`.
  `time` is the departure time in seconds; `path` is the route from where the
  responder is at that moment to the incident. Sorted by departure, then responder.
- **`statistics.txt`**: incidents handled, responders used, average response
  time and the percentage of deadlines met, followed by deadlines per priority,
  late and unhandled incidents, the validation result and the definitions used.
  All times are seconds of simulation time; these first numbers use the model's
  *expected* travel times.
  An unhandled incident counts as a missed deadline.
  A last section executes the plan in sampled true road states (Monte Carlo),
  where responders detour around roads they find blocked; it reports the
  deadlines really met with a 95% confidence interval and P(on time) per incident.

After writing `plan.json`, `run.py` reads it back and validates it
(`emergency/plan/validator.py`; the error and warning codes are listed at the top of that file).

## Sensitivity analysis

```bash
python3 evaluate.py --out results/evaluation.txt
```

For every scenario this prints a table with Monte Carlo results for plans made
with another `tau` or without revise (paired with the base plan, in the same
sampled worlds), and for the base plan in worlds sampled from another model
(stationary traffic, Storm on the roads without reports). Options:
`--samples N` (default 1000), `--seed S`, and scenario names to run only those.

## Project structure

```
run.py                  entry point
evaluate.py             Monte Carlo sensitivity analysis
emergency/data/         loading and checking the scenario files
emergency/world/        Bayesian network + HMM -> expected cost per road
emergency/search/       uniform-cost search (one source to all nodes)
emergency/allocation/   CSP per event + event loop over the incident timestamps
emergency/plan/         plan.json, validator, statistics.txt
emergency/evaluation/   Monte Carlo evaluation of a plan
tests/                  pytest test suite
Scenarios/              the three given scenarios
LOGBOEK.md              development log (Dutch): choices, alternatives, LLM use
report/report.tex       the report (LaTeX, compiled on Overleaf)
```

## Tests

```bash
python3 -m pytest
```
