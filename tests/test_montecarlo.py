"""Tests for the Monte Carlo evaluation (emergency/evaluation), step 5a.

Sampling is checked against the distributions it draws from; execution on a
small hand-made city whose sampled travel times are set by hand:

         10        10
    A ------> B ------> G        expected costs (what the responder believes);
    |         |         ^        the true time of each road is set per test
    | 15      | 100     | 15
    +-------> C --------+
"""

import dataclasses
import math
from pathlib import Path

import pytest

import run
from emergency.allocation import Assignment, simulate
from emergency.data import Incident, Priority, Responder, ResponderType, RoadStatus, TrafficLevel, load_scenario
from emergency.evaluation import MonteCarloResult, SampledWorld, evaluate, execute, format_monte_carlo, sample_worlds
from emergency.world import RoadBelief, WorldModel, build_world
from tests.helpers import toy_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]
EXPECTED = {("A", "B"): 10, ("B", "G"): 10, ("A", "C"): 15, ("B", "C"): 100, ("C", "G"): 15}


@pytest.fixture(scope="module")
def s1():
    return load_scenario(SCENARIOS / "Scenario1")


def city(s1, tasks, deadline=1000.0, time_required=0.0):
    """Scenario with responder R at A and one incident per (incident id, location) in `tasks`."""
    incidents = tuple(Incident(iid, loc, Priority.HIGH, deadline, "X", 0.0, time_required) for iid, loc in tasks)
    responders = (Responder("R", ResponderType.AMBULANCE, "A", frozenset({"X"}), 0.0),)
    return dataclasses.replace(s1, incidents=incidents, responders=responders)


def task(incident_id, path, departure=0.0):
    return Assignment("R", incident_id, tuple(path), departure, 0.0, 0.0)


def sampled(blocked=(), roads=EXPECTED, **times):
    """True travel times; every road takes 1 s unless given, e.g. AB=7."""
    time = {edge: times.get("".join(edge), 1.0) for edge in roads if edge not in blocked}
    return SampledWorld(frozenset(blocked), time)


# --------------------------------------------------------------------------- #
# Sampling
# --------------------------------------------------------------------------- #

def certain_world(status, traffic):
    world = toy_world({("A", "B"): 1.0})  # base time 1 s
    belief = RoadBelief({s: float(s is status) for s in RoadStatus},
                        {t: float(t is traffic) for t in TrafficLevel}, 1.0)
    return WorldModel(world.graph, {("A", "B"): belief}, world.params)


@pytest.mark.parametrize("status, traffic, time", [
    (RoadStatus.OPEN, TrafficLevel.LOW, 1.0),
    (RoadStatus.OPEN, TrafficLevel.HIGH, 1.5),
    (RoadStatus.CONGESTED, TrafficLevel.MEDIUM, 1.5 * 1.2),
    (RoadStatus.CONGESTED, TrafficLevel.HIGH, 1.5 * 1.5),
])
def test_travel_time_of_a_sampled_road(status, traffic, time):
    (world,) = sample_worlds(certain_world(status, traffic), 1, seed=0)
    assert world.blocked == frozenset() and world.time == {("A", "B"): pytest.approx(time)}


def test_blocked_road_has_no_travel_time():
    (world,) = sample_worlds(certain_world(RoadStatus.BLOCKED, TrafficLevel.LOW), 1, seed=0)
    assert world.blocked == {("A", "B")} and world.time == {}


def test_sampled_frequencies_follow_the_beliefs(s1):
    world = build_world(s1)
    n = 4000
    worlds = sample_worlds(world, n, seed=1)
    reported, unreported, observed = ("N1", "N2"), ("H1", "N4"), ("H1", "N1")
    for edge in (reported, unreported):
        p = world.beliefs[edge].p_blocked
        freq = sum(edge in w.blocked for w in worlds) / n
        assert abs(freq - p) < 4 * math.sqrt(p * (1 - p) / n)  # 4 standard errors
    # Slowdown factor (status x traffic) of a road that is not blocked. Note that
    # Open + High and Congested + Low both give 1.5.
    belief, params = world.beliefs[observed], world.params
    status_factor = {RoadStatus.OPEN: 1.0, RoadStatus.CONGESTED: params.congested_factor}
    expected = {}
    for s, c in status_factor.items():
        for level, m in params.traffic_factors.items():
            f = round(c * m, 6)
            expected[f] = expected.get(f, 0) + belief.status[s] * belief.traffic[level] / (1 - belief.p_blocked)
    factors = [round(w.time[observed] / s1.graph.road(*observed).base_time, 6) for w in worlds if observed in w.time]
    for f, p in expected.items():
        freq = factors.count(f) / len(factors)
        assert abs(freq - p) < 4 * math.sqrt(p * (1 - p) / len(factors)) + 1e-3, f
    assert set(factors) <= set(expected)


def test_sampling_is_reproducible(s1):
    world = build_world(s1)
    assert sample_worlds(world, 20, seed=3) == sample_worlds(world, 20, seed=3)
    assert sample_worlds(world, 20, seed=3) != sample_worlds(world, 20, seed=4)


# --------------------------------------------------------------------------- #
# Execution of a fixed plan
# --------------------------------------------------------------------------- #

def test_follows_the_planned_path_with_the_true_times(s1):
    arrival = execute(city(s1, [("I1", "G")]), [task("I1", "ABG")], toy_world(EXPECTED), sampled(AB=12, BG=9))
    assert arrival == {"I1": 21}


def test_never_leaves_before_the_planned_departure(s1):
    arrival = execute(city(s1, [("I1", "G")]), [task("I1", "ABG", departure=50)], toy_world(EXPECTED), sampled())
    assert arrival == {"I1": 52}


def test_delay_moves_on_to_the_next_task(s1):
    # Planned: I1 at B at 10, busy 5, so I2 leaves B at 15. It really arrives at B at 30.
    scenario = city(s1, [("I1", "B"), ("I2", "G")], time_required=5)
    plan = [task("I1", "AB"), task("I2", "BG", departure=15)]
    assert execute(scenario, plan, toy_world(EXPECTED), sampled(AB=30, BG=10)) == {"I1": 30, "I2": 45}


def test_detours_at_the_start_of_a_blocked_road(s1):
    # B->G is blocked: the responder only sees it at B and continues via C.
    arrival = execute(city(s1, [("I1", "G")]), [task("I1", "ABG")], toy_world(EXPECTED),
                      sampled(blocked=[("B", "G")], AB=10, BC=100, CG=15))
    assert arrival == {"I1": 125}


def test_detour_is_the_cheapest_one_the_responder_believes_in(s1):
    # From B two detours: via C (expected 115) and via D (expected 10). Via D is
    # taken, with the true times; a planner road with P(Blocked) > tau (None) is avoided.
    roads = {**EXPECTED, ("B", "D"): 5, ("D", "G"): 5}
    true = dict(blocked=[("B", "G")], roads=roads, AB=10, BC=100, CG=15, BD=6, DG=6)
    plan = [task("I1", "ABG")]
    assert execute(city(s1, [("I1", "G")]), plan, toy_world(roads), sampled(**true)) == {"I1": 22}
    unusable = {**roads, ("B", "D"): None}  # really open, but the responder thinks it is blocked
    assert execute(city(s1, [("I1", "G")]), plan, toy_world(unusable), sampled(**true)) == {"I1": 125}


def test_two_blocked_roads_on_the_way(s1):
    # Planned A->B->G. B->G is blocked, the detour B->C->G too (C->G blocked): no route left.
    scenario = city(s1, [("I1", "G"), ("I2", "B")])
    plan = [task("I1", "ABG"), task("I2", "GB", departure=100)]  # planner thought R would be at G
    roads = {**EXPECTED, ("G", "B"): 5, ("C", "B"): 1}
    arrival = execute(scenario, plan, toy_world(roads),
                      sampled(blocked=[("B", "G"), ("C", "G")], roads=roads, AB=10, BC=100, CB=1))
    # I1 fails at C (110 s); I2 is then reached from C, at max(100, 110) + 1.
    assert arrival == {"I2": 111}


def test_failed_incident_counts_as_not_reached(s1):
    arrival = execute(city(s1, [("I1", "G")]), [task("I1", "ABG")], toy_world(EXPECTED),
                      sampled(blocked=[("B", "G"), ("C", "G")]))
    assert arrival == {}


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_expected_world_gives_the_planned_arrivals(name, revise):
    # No road blocked and every road at its expected time: execution = the plan.
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    plan = simulate(s, world, revise=revise).assignments
    expected = SampledWorld(frozenset(), {e: world.cost(*e) for e in s.graph.roads if world.cost(*e) is not None})
    arrival = execute(s, plan, world, expected)
    assert arrival == {a.incident_id: pytest.approx(a.arrival, abs=1e-9) for a in plan}


# --------------------------------------------------------------------------- #
# evaluate, confidence interval, output
# --------------------------------------------------------------------------- #

def test_evaluate_by_hand(s1):
    # Deadline 20. World 1: exactly 20 s (on time). World 2: 30 s (late). World 3: blocked (not reached).
    scenario = city(s1, [("I1", "G"), ("I2", "A")], deadline=20)
    plan = [task("I1", "ABG")]  # I2 is not in the plan
    worlds = [sampled(AB=10, BG=10), sampled(AB=20, BG=10), sampled(blocked=[("B", "G"), ("C", "G")])]
    result = evaluate(scenario, plan, toy_world(EXPECTED), worlds)
    assert result.met == (50.0, 0.0, 0.0)  # divided by both incidents
    assert result.response == (20, 30)  # world 3 reached nothing
    assert result.not_reached == (0, 0, 1)
    assert result.p_on_time == {"I1": pytest.approx(1 / 3), "I2": 0.0}


def test_mean_and_confidence_interval():
    mean, half = MonteCarloResult.mean_ci([0.0, 100.0])
    assert mean == 50 and half == pytest.approx(1.96 * math.sqrt(5000) / math.sqrt(2))
    mean, half = MonteCarloResult.mean_ci([42.0])
    assert mean == 42 and math.isnan(half)


def test_monte_carlo_text():
    result = MonteCarloResult((50.0, 100.0), (20.0, 30.0), (1, 0), {"I1": 0.5, "I2": 1.0})
    text = format_monte_carlo(result, seed=9)
    assert "2 sampled worlds, seed 9" in text and " * Deadlines met : 75.0% +- " in text
    assert " * Incidents not reached : 0.50 per world" in text and "I1 0.50, I2 1.00" in text


def test_run_adds_monte_carlo_only_when_asked(tmp_path):
    assert run.main(["--out", str(tmp_path / "a"), "--samples", "200"]) == 0
    assert run.main(["--out", str(tmp_path / "b"), "--samples", "200"]) == 0
    assert run.main(["--out", str(tmp_path / "c"), "--samples", "0"]) == 0
    text = (tmp_path / "a" / "statistics.txt").read_text()
    assert "Monte Carlo (200 sampled worlds, seed 0)" in text
    assert text == (tmp_path / "b" / "statistics.txt").read_text()  # reproducible
    assert "Monte Carlo" not in (tmp_path / "c" / "statistics.txt").read_text()
    with pytest.raises(SystemExit):
        run.main(["--samples", "-1"])
