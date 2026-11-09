"""Tests for the world model (emergency/world).

Expected values are hand calculations written out with the numbers from
Scenarios/Scenario1/*.json, so each one can be checked on paper.
"""

import math
from pathlib import Path

import pytest

from emergency.data import (
    ReportSource,
    RoadEvidence,
    RoadReport,
    RoadStatus,
    TrafficLevel,
    Weather,
    load_scenario,
)
from emergency.world import (
    WorldParams,
    build_world,
    expected_travel_time,
    filter_traffic,
    road_posterior,
    status_prior,
)
from emergency.world.distributions import normalize

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]

O, C, B = RoadStatus.OPEN, RoadStatus.CONGESTED, RoadStatus.BLOCKED
LOW, MED, HIGH = TrafficLevel.LOW, TrafficLevel.MEDIUM, TrafficLevel.HIGH


@pytest.fixture(scope="module")
def s1():
    return load_scenario(SCENARIOS / "Scenario1")


def status(p_open, p_congested, p_blocked):
    return {O: p_open, C: p_congested, B: p_blocked}


def traffic(p_low, p_medium, p_high):
    return {LOW: p_low, MED: p_medium, HIGH: p_high}


def evidence(weather, *reports):
    return RoadEvidence(weather, tuple(RoadReport(src, rep) for src, rep in reports))


def assert_dist(actual, expected):
    assert actual.keys() == expected.keys()
    for key in expected:
        assert actual[key] == pytest.approx(expected[key]), key


# --------------------------------------------------------------------------- #
# Bayes: road status
# --------------------------------------------------------------------------- #

def test_prior_with_known_weather_is_the_cpt_row(s1):
    assert_dist(status_prior(s1.road_cpts, Weather.RAIN), status(0.60, 0.30, 0.10))


def test_prior_with_unknown_weather_is_marginalized(s1):
    # Σ_w P(w)·P(S|w) with P(w) = 0.5 / 0.3 / 0.2 (Clear / Rain / Storm)
    expected = status(0.5 * 0.95 + 0.3 * 0.60 + 0.2 * 0.15,   # 0.685
                      0.5 * 0.04 + 0.3 * 0.30 + 0.2 * 0.35,   # 0.18
                      0.5 * 0.01 + 0.3 * 0.10 + 0.2 * 0.50)   # 0.135
    assert_dist(status_prior(s1.road_cpts, None), expected)
    assert_dist(road_posterior(s1.road_cpts, None), expected)


def test_posterior_single_police_report(s1):
    # Rain prior × P(Police says Blocked | S), then normalize.
    ev = evidence(Weather.RAIN, (ReportSource.POLICE, B))
    expected = normalize(status(0.6 * 0.02, 0.3 * 0.08, 0.1 * 0.90))  # 0.095 / 0.190 / 0.714
    assert_dist(road_posterior(s1.road_cpts, ev), expected)


def test_posterior_n1_n2_three_reports(s1):
    # Rain; Citizen=Blocked, Police=Blocked, Sensor=Congested.
    expected = normalize(status(0.6 * 0.10 * 0.02 * 0.10,
                                0.3 * 0.20 * 0.08 * 0.80,
                                0.1 * 0.70 * 0.90 * 0.07))  # 0.014 / 0.459 / 0.527
    assert_dist(road_posterior(s1.road_cpts, s1.road_evidence[("N1", "N2")]), expected)


def test_report_order_does_not_matter(s1):
    ev = s1.road_evidence[("N1", "N2")]
    reversed_ev = RoadEvidence(ev.weather, ev.reports[::-1])
    assert_dist(road_posterior(s1.road_cpts, reversed_ev), road_posterior(s1.road_cpts, ev))


def test_extra_agreeing_report_increases_belief(s1):
    one = evidence(Weather.RAIN, (ReportSource.CITIZEN, B))
    two = evidence(Weather.RAIN, (ReportSource.CITIZEN, B), (ReportSource.SENSOR, B))
    assert road_posterior(s1.road_cpts, two)[B] > road_posterior(s1.road_cpts, one)[B]


def test_worse_weather_increases_p_blocked_for_same_reports(s1):
    reports = [(ReportSource.CITIZEN, C), (ReportSource.SENSOR, C)]
    p = {w: road_posterior(s1.road_cpts, evidence(w, *reports))[B] for w in Weather}
    assert p[Weather.CLEAR] < p[Weather.RAIN] < p[Weather.STORM]


def test_impossible_evidence_cannot_be_normalized():
    with pytest.raises(ValueError):
        normalize({O: 0.0, C: 0.0, B: 0.0})


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_every_belief_is_a_distribution(name):
    for belief in build_world(load_scenario(SCENARIOS / name)).beliefs.values():
        for dist in (belief.status, belief.traffic):
            assert sum(dist.values()) == pytest.approx(1.0)
            assert all(0.0 <= p <= 1.0 for p in dist.values())


# --------------------------------------------------------------------------- #
# HMM: traffic filtering
# --------------------------------------------------------------------------- #

def test_no_observations_gives_initial(s1):
    assert_dist(filter_traffic(s1.hmm, ()), traffic(0.6, 0.3, 0.1))


def test_one_observation(s1):
    # f_1 = α · P(e=Low | X) · P(X_1)
    expected = normalize(traffic(0.6 * 0.85, 0.3 * 0.10, 0.1 * 0.02))  # 0.941 / 0.055 / 0.004
    assert_dist(filter_traffic(s1.hmm, [LOW]), expected)


def test_two_observations(s1):
    f1 = normalize(traffic(0.6 * 0.85, 0.3 * 0.10, 0.1 * 0.02))
    # predict: Σ_x P(X_2 | x)·f_1(x), then weight by P(e=High | X_2) = 0.01 / 0.10 / 0.80
    predicted = traffic(f1[LOW] * 0.80 + f1[MED] * 0.15 + f1[HIGH] * 0.05,
                        f1[LOW] * 0.18 + f1[MED] * 0.70 + f1[HIGH] * 0.20,
                        f1[LOW] * 0.02 + f1[MED] * 0.15 + f1[HIGH] * 0.75)
    expected = normalize(traffic(predicted[LOW] * 0.01, predicted[MED] * 0.10, predicted[HIGH] * 0.80))
    assert_dist(filter_traffic(s1.hmm, [LOW, HIGH]), expected)  # 0.145 / 0.399 / 0.456


def test_history_matters_not_only_last_observation(s1):
    # A long Low history makes one Medium observation less convincing.
    only_last = filter_traffic(s1.hmm, [MED])
    with_history = filter_traffic(s1.hmm, [LOW] * 9 + [MED])
    assert with_history[LOW] > only_last[LOW]


def test_long_sequence_does_not_underflow(s1):
    belief = filter_traffic(s1.hmm, [HIGH] * 2000)
    assert sum(belief.values()) == pytest.approx(1.0)
    assert belief[HIGH] > 0.9


# --------------------------------------------------------------------------- #
# Cost per road
# --------------------------------------------------------------------------- #

PARAMS = WorldParams()  # τ = 0.5, congested 1.5, traffic 1.0 / 1.2 / 1.5


def test_certainly_open_and_low_traffic_costs_base_time():
    assert expected_travel_time(100, status(1, 0, 0), traffic(1, 0, 0), PARAMS) == pytest.approx(100)


def test_cost_formula_by_hand():
    # status factor (0.3 + 1.5·0.3) / 0.6 = 1.25; traffic factor 0.5·1.0 + 0.5·1.5 = 1.25
    cost = expected_travel_time(100, status(0.3, 0.3, 0.4), traffic(0.5, 0, 0.5), PARAMS)
    assert cost == pytest.approx(100 * 1.25 * 1.25)


def test_blocked_threshold_boundary():
    # Design choice 2: unusable only when P(Blocked) > τ.
    assert expected_travel_time(100, status(0.5, 0.0, 0.5), traffic(1, 0, 0), PARAMS) is not None
    assert expected_travel_time(100, status(0.49, 0.0, 0.51), traffic(1, 0, 0), PARAMS) is None


def test_certainly_blocked_with_threshold_one_does_not_divide_by_zero():
    params = WorldParams(blocked_threshold=1.0)
    assert expected_travel_time(100, status(0, 0, 1), traffic(1, 0, 0), params) is None


@pytest.mark.parametrize("bad", [
    dict(congested_factor=0.9),
    dict(traffic_factors={LOW: 0.8, MED: 1.2, HIGH: 1.5}),
    dict(traffic_factors={LOW: 1.0, HIGH: 1.5}),
])
def test_params_reject_factors_that_break_admissibility(bad):
    with pytest.raises(ValueError):
        WorldParams(**bad)


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_costs_stay_between_base_time_and_max_slowdown(name):
    # Lower bound keeps the A* heuristic admissible; upper bound = 1.5 (status) × 1.5 (traffic).
    s = load_scenario(SCENARIOS / name)
    for edge, belief in build_world(s).beliefs.items():
        if belief.usable:
            base = s.graph.roads[edge].base_time
            assert base <= belief.expected_time <= base * 1.5 * 1.5 + 1e-9


def test_unreported_unobserved_road_uses_both_defaults():
    # Scenario 2 has roads with neither reports nor traffic data.
    s = load_scenario(SCENARIOS / "Scenario2")
    edge = next(e for e in s.graph.roads if e not in s.road_evidence and e not in s.traffic_observations)
    status_factor = (0.685 + 1.5 * 0.18) / (0.685 + 0.18)  # marginalized weather
    traffic_factor = 0.50 * 1.0 + 0.35 * 1.2 + 0.15 * 1.5  # Scenario 2 `initial`
    expected = s.graph.roads[edge].base_time * status_factor * traffic_factor
    assert build_world(s).cost(*edge) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# WorldModel on the scenarios
# --------------------------------------------------------------------------- #

def test_scenario1_unusable_roads_and_neighbors(s1):
    world = build_world(s1)
    unusable = {edge for edge, b in world.beliefs.items() if not b.usable}
    assert unusable == {("N1", "N2"), ("N2", "N4"), ("H1", "N3"), ("N3", "H1")}
    assert world.cost("N1", "N2") is None
    assert world.cost("N1", "N3") is None  # road does not exist
    assert [n for n, _ in world.neighbors("N1")] == ["H1"]


def test_world_uses_each_roads_own_reports_and_observations(s1):
    belief = build_world(s1).beliefs[("H1", "N1")]
    observations = s1.traffic_observations[("H1", "N1")]
    assert_dist(belief.traffic, filter_traffic(s1.hmm, observations))
    assert belief.traffic[LOW] != pytest.approx(s1.hmm.initial[LOW])  # not the fallback
    assert_dist(build_world(s1).beliefs[("N1", "N2")].status,
                road_posterior(s1.road_cpts, s1.road_evidence[("N1", "N2")]))


def test_route_reliability(s1):
    world = build_world(s1)
    assert world.route_reliability(["H1"]) == 1.0  # no roads, nothing can be blocked
    assert world.route_reliability(["H1", "N1"]) == pytest.approx(1 - 0.135)
    two_roads = ["H1", "N1", "H1"]
    assert world.route_reliability(two_roads) == pytest.approx(
        math.prod(1 - world.beliefs[e].p_blocked for e in [("H1", "N1"), ("N1", "H1")]))
    with pytest.raises(KeyError):
        world.route_reliability(["N1", "N3"])


def test_scenario2_bridge_depends_on_threshold():
    # N1<->N2 is the only link between the two halves of the city (P(Blocked) ≈ 0.83).
    s = load_scenario(SCENARIOS / "Scenario2")
    default = build_world(s)
    assert default.beliefs[("N1", "N2")].p_blocked == pytest.approx(0.83, abs=0.005)
    assert default.cost("N1", "N2") is None and default.cost("N2", "N1") is None
    lenient = build_world(s, WorldParams(blocked_threshold=0.9))
    assert lenient.cost("N1", "N2") is not None
