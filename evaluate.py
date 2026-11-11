"""Sensitivity analysis with Monte Carlo (design choice 18).

    python evaluate.py [SCENARIO ...] [--samples N] [--seed S] [--out FILE]

Two kinds of variants per scenario:
  decisions  plans made with another tau or without revise, executed in the
             same sampled worlds as the base plan (common random numbers), so
             "vs base" is a paired difference with its own 95% interval
  truth      the base plan, executed in worlds sampled from another model for
             the roads without data: traffic from the stationary distribution
             of the HMM instead of `initial`, or Storm instead of the weather
             prior. This asks how robust the plan is when our model is wrong.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

from emergency.allocation import simulate
from emergency.data import HMMParams, Scenario, Weather, load_scenario
from emergency.evaluation import MonteCarloResult, evaluate, sample_worlds
from emergency.plan import compute_statistics
from emergency.world import WorldModel, WorldParams, build_world

SCENARIOS = Path(__file__).resolve().parent / "Scenarios"
BASE_TAU = WorldParams().blocked_threshold
DECISIONS = [("base (tau 0.5, revise)", BASE_TAU, True), ("tau 0.3", 0.3, True), ("tau 0.7", 0.7, True),
             ("tau 0.9", 0.9, True), ("no revise", BASE_TAU, False)]
TRUTHS = ["stationary traffic", "storm"]


def stationary(hmm: HMMParams, iterations: int = 1000) -> dict:
    """π with π = π·T, by repeatedly applying the transition model to `initial`."""
    p = dict(hmm.initial)
    for _ in range(iterations):
        p = {to: sum(p[frm] * hmm.transition[frm][to] for frm in p) for to in p}
    return p


def truth_variant(scenario: Scenario, world: WorldModel, kind: str) -> WorldModel:
    """The same beliefs, except for the roads without traffic observations or without reports."""
    if kind not in TRUTHS:
        raise ValueError(f"unknown truth variant {kind!r}")
    beliefs = {}
    for edge, belief in world.beliefs.items():
        if kind == "stationary traffic" and edge not in scenario.traffic_observations:
            belief = dataclasses.replace(belief, traffic=stationary(scenario.hmm))
        elif kind == "storm" and edge not in scenario.road_evidence:
            belief = dataclasses.replace(belief, status=dict(scenario.road_cpts.status_given_weather[Weather.STORM]))
        beliefs[edge] = belief
    return WorldModel(world.graph, beliefs, world.params)


def analyse(scenario: Scenario, samples: int, seed: int) -> list[tuple[str, float, MonteCarloResult]]:
    """(variant, predicted % deadlines met, Monte Carlo result); the first row is the base."""
    base = build_world(scenario)
    worlds = sample_worlds(base, samples, seed)
    rows = []
    for name, tau, revise in DECISIONS:
        world = build_world(scenario, WorldParams(blocked_threshold=tau))
        plan = simulate(scenario, world, revise=revise).assignments
        rows.append((name, compute_statistics(scenario, plan).met_percentage,
                     evaluate(scenario, plan, world, worlds)))
    base_plan = simulate(scenario, base, revise=True).assignments
    for kind in TRUTHS:
        truth_worlds = sample_worlds(truth_variant(scenario, base, kind), samples, seed)
        rows.append((f"truth: {kind}", rows[0][1], evaluate(scenario, base_plan, base, truth_worlds)))
    return rows


def format_table(name: str, rows: list[tuple[str, float, MonteCarloResult]], seed: int) -> str:
    base = rows[0][2]
    lines = [f"{name} ({len(base.met)} sampled worlds, seed {seed}); % = deadlines met",
             f"{'variant':<26}{'predicted':>10}{'Monte Carlo':>16}{'vs base':>16}{'not reached':>13}{'response':>10}"]
    for variant, predicted, result in rows:
        met, ci = result.mean_ci(result.met)
        if variant.startswith("truth") or result is base:
            diff = "-"
        else:
            d, d_ci = result.mean_ci([a - b for a, b in zip(result.met, base.met)])
            diff = f"{d:+.1f} +- {d_ci:.1f}"
        not_reached = sum(result.not_reached) / len(result.not_reached)
        lines.append(f"{variant:<26}{predicted:>9.1f}%{f'{met:.1f}% +- {ci:.1f}':>16}{diff:>16}"
                     f"{not_reached:>13.2f}{result.mean_ci(result.response)[0]:>9.1f}s")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monte Carlo sensitivity analysis of the plans.")
    parser.add_argument("scenarios", nargs="*", default=["Scenario1", "Scenario2", "Scenario3"],
                        help="names of folders in Scenarios/ (default: all three)")
    parser.add_argument("--samples", type=int, default=1000, help="sampled worlds (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=0, help="seed of the sampling (default: 0)")
    parser.add_argument("--out", type=Path, help="also write the tables to this file")
    args = parser.parse_args(argv)
    if args.samples < 2:
        parser.error("--samples must be >= 2 (a confidence interval needs two values)")
    tables = [format_table(name, analyse(load_scenario(SCENARIOS / name), args.samples, args.seed), args.seed)
              for name in args.scenarios]
    text = "\n".join(tables)
    print(text, end="")
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
