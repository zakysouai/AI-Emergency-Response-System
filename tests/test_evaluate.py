"""Tests for the sensitivity analysis (evaluate.py), step 5b.

The stationary distribution is checked by hand and as a fixed point, the truth
variants road by road, and the table on hand-made Monte Carlo results, so the
paired difference "vs base" can be computed on paper.
"""

import math
from pathlib import Path

import pytest

import evaluate
from emergency.allocation import simulate
from emergency.data import HMMParams, TrafficLevel, Weather, load_scenario
from emergency.evaluation import MonteCarloResult
from emergency.plan import compute_statistics
from emergency.world import build_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
LOW, MEDIUM, HIGH = TrafficLevel.LOW, TrafficLevel.MEDIUM, TrafficLevel.HIGH


@pytest.fixture(scope="module")
def s2():
    return load_scenario(SCENARIOS / "Scenario2")  # only 3 of the 30 roads have traffic observations


# --------------------------------------------------------------------------- #
# Stationary distribution and truth variants
# --------------------------------------------------------------------------- #

def test_stationary_distribution_by_hand():
    # Two states: pi_L = 0.9 pi_L + 0.5 pi_H  ->  pi_L = 5 pi_H  ->  (5/6, 1/6).
    hmm = HMMParams({LOW: 1.0, HIGH: 0.0}, {LOW: {LOW: 0.9, HIGH: 0.1}, HIGH: {LOW: 0.5, HIGH: 0.5}}, {})
    pi = evaluate.stationary(hmm)
    assert pi[LOW] == pytest.approx(5 / 6) and pi[HIGH] == pytest.approx(1 / 6)


@pytest.mark.parametrize("name", ["Scenario1", "Scenario2", "Scenario3"])
def test_stationary_distribution_of_the_scenarios_is_a_fixed_point(name):
    hmm = load_scenario(SCENARIOS / name).hmm  # every scenario has its own HMM
    pi = evaluate.stationary(hmm)
    assert sum(pi.values()) == pytest.approx(1)
    for to in pi:
        assert sum(pi[frm] * hmm.transition[frm][to] for frm in pi) == pytest.approx(pi[to])


def test_stationary_distribution_of_scenario1():
    pi = evaluate.stationary(load_scenario(SCENARIOS / "Scenario1").hmm)
    assert (pi[LOW], pi[MEDIUM], pi[HIGH]) == pytest.approx((0.354, 0.386, 0.260), abs=1e-3)


def test_stationary_traffic_only_changes_roads_without_observations(s2):
    base = build_world(s2)
    truth = evaluate.truth_variant(s2, base, "stationary traffic")
    pi = evaluate.stationary(s2.hmm)
    for edge, belief in truth.beliefs.items():
        assert belief.status == base.beliefs[edge].status
        expected = base.beliefs[edge].traffic if edge in s2.traffic_observations else pi
        assert belief.traffic == pytest.approx(expected)
    assert len(s2.traffic_observations) == 3


def test_storm_only_changes_roads_without_reports(s2):
    base = build_world(s2)
    truth = evaluate.truth_variant(s2, base, "storm")
    storm = s2.road_cpts.status_given_weather[Weather.STORM]
    for edge, belief in truth.beliefs.items():
        assert belief.traffic == base.beliefs[edge].traffic
        expected = base.beliefs[edge].status if edge in s2.road_evidence else storm
        assert belief.status == expected


def test_unknown_truth_variant_is_refused(s2):
    with pytest.raises(ValueError):
        evaluate.truth_variant(s2, build_world(s2), "hail")


# --------------------------------------------------------------------------- #
# analyse
# --------------------------------------------------------------------------- #

def test_analyse_rows(s2):
    rows = evaluate.analyse(s2, samples=50, seed=0)
    assert [name for name, _, _ in rows] == [name for name, _, _ in evaluate.DECISIONS] + \
        [f"truth: {kind}" for kind in evaluate.TRUTHS]
    base_plan = simulate(s2, build_world(s2), revise=True).assignments
    assert all(predicted == compute_statistics(s2, base_plan).met_percentage for _, predicted, _ in rows)
    assert all(len(result.met) == 50 for _, _, result in rows)


def test_decision_variants_really_change_the_plan_in_scenario3():
    # Predicted % per variant = the plan made with that tau / revise (see LOGBOEK 5b).
    s3 = load_scenario(SCENARIOS / "Scenario3")
    predicted = {name: p for name, p, _ in evaluate.analyse(s3, samples=10, seed=0)}
    assert predicted["base (tau 0.5, revise)"] == pytest.approx(55.0)
    assert predicted["tau 0.7"] == pytest.approx(50.0) and predicted["no revise"] == pytest.approx(50.0)


def test_same_plan_in_the_same_worlds_gives_the_same_results(s2):
    # In S2 no tau changes the plan, so with common random numbers every
    # decision row must be identical to the base row, world by world.
    rows = evaluate.analyse(s2, samples=50, seed=0)
    base = rows[0][2]
    for name, _, result in rows[1:len(evaluate.DECISIONS)]:
        assert result.met == base.met, name
    assert rows[-1][2].met != base.met  # Storm: other worlds


def test_analyse_is_reproducible(s2):
    assert evaluate.analyse(s2, 30, seed=5) == evaluate.analyse(s2, 30, seed=5)


# --------------------------------------------------------------------------- #
# Table and command line
# --------------------------------------------------------------------------- #

def result(met):
    return MonteCarloResult(tuple(met), (10.0,) * len(met), (0,) * len(met), {})


def test_vs_base_is_a_paired_difference():
    # Per world the variant is exactly 10 points better: +10 with an interval of 0,
    # although each mean on its own has a wide interval.
    rows = [("base (tau 0.5, revise)", 50.0, result([0, 100, 50])),
            ("tau 0.7", 50.0, result([10, 110, 60])),
            ("truth: storm", 50.0, result([0, 0, 0]))]
    lines = evaluate.format_table("Toy", rows, seed=0).splitlines()
    assert lines[0] == "Toy (3 sampled worlds, seed 0); % = deadlines met"
    assert lines[3].split()[3:9] == ["60.0%", "+-", "56.6", "+10.0", "+-", "0.0"]  # "tau 0.7" is 2 words
    assert lines[2].split()[-3] == "-" and lines[4].split()[-3] == "-"  # base and truth rows: no difference
    assert math.isclose(1.96 * 50 / math.sqrt(3), 56.58, abs_tol=0.01)


def test_main_writes_the_tables(tmp_path, capsys):
    out = tmp_path / "evaluation.txt"
    assert evaluate.main(["Scenario1", "--samples", "20", "--out", str(out)]) == 0
    text = out.read_text()
    assert text == capsys.readouterr().out
    assert text.startswith("Scenario1 (20 sampled worlds, seed 0)") and "Scenario2" not in text
    assert len(text.splitlines()) == 2 + len(evaluate.DECISIONS) + len(evaluate.TRUTHS)


def test_too_few_samples_is_a_usage_error():
    with pytest.raises(SystemExit):
        evaluate.main(["--samples", "1"])
