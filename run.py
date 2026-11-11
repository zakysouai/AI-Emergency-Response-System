"""Entry point (design choice 13): plan one scenario and write plan.json + statistics.txt.

    python run.py [SCENARIO] [--out DIR] [--no-revise] [--tau TAU]

SCENARIO is the name of a folder in Scenarios/ (default: Scenario1) or a path
to any scenario folder. The written plan.json is read back and validated. Exit code 0 means
a valid plan, 1 an invalid plan, 2 unusable input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emergency.allocation import simulate
from emergency.data import DataError, load_scenario
from emergency.plan import compute_statistics, format_statistics, validate_plan_text, write_plan
from emergency.world import WorldParams, build_world

SCENARIOS = Path(__file__).resolve().parent / "Scenarios"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Storm emergency response: plan one scenario.")
    parser.add_argument("scenario", nargs="?", default="Scenario1",
                        help="scenario folder, or a name in Scenarios/ (default: Scenario1)")
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="folder for plan.json and statistics.txt (default: current folder)")
    parser.add_argument("--no-revise", action="store_true",
                        help="never re-plan tasks that have not departed yet (option A)")
    parser.add_argument("--tau", type=float, default=WorldParams().blocked_threshold,
                        help="a road is unusable when P(Blocked) > TAU (default: %(default)s)")
    args = parser.parse_args(argv)
    if not 0 <= args.tau <= 1:
        parser.error("--tau must lie between 0 and 1")

    # A bare name such as "Scenario2" means Scenarios/Scenario2, even when the
    # current folder happens to contain a folder with that name (e.g. old output).
    folder = Path(args.scenario)
    if len(folder.parts) == 1 and (SCENARIOS / args.scenario).is_dir():
        folder = SCENARIOS / args.scenario
    try:
        scenario = load_scenario(folder)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for warning in scenario.warnings:
        print(f"data warning: {warning}")

    revise = not args.no_revise
    world = build_world(scenario, WorldParams(blocked_threshold=args.tau))
    result = simulate(scenario, world, revise=revise)
    for warning in result.warnings:
        print(f"planner warning: {warning}")

    args.out.mkdir(parents=True, exist_ok=True)
    plan_path, stats_path = args.out / "plan.json", args.out / "statistics.txt"
    write_plan(plan_path, result.assignments)
    report = validate_plan_text(plan_path.read_text(encoding="utf-8"), scenario, world)
    settings = {"tau": args.tau, "revise": revise}
    text = format_statistics(compute_statistics(scenario, result.assignments),
                             scenario.name, settings, report)
    stats_path.write_text(text, encoding="utf-8")

    print(text, end="")
    print(f"\nWrote {plan_path} and {stats_path}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())
