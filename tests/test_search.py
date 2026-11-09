"""Tests for uniform-cost search (emergency/search).

Small hand-made worlds check the algorithm itself (each one targets one way
UCS can go wrong); the scenarios check it on the real data, against routes
worked out by hand and against an independent brute-force algorithm.
"""

import math
from pathlib import Path

import pytest

from emergency.data import load_scenario
from emergency.search import travel_table, uniform_cost_search
from emergency.world import WorldParams, build_world
from tests.helpers import toy_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]


def bellman_ford(world, source):
    """Independent check: relax every usable road |V| - 1 times."""
    dist = {node: math.inf for node in world.graph.nodes}
    dist[source] = 0.0
    for _ in range(len(dist) - 1):
        for node in world.graph.nodes:
            for nxt, cost in world.neighbors(node):
                dist[nxt] = min(dist[nxt], dist[node] + cost)
    return {node: d for node, d in dist.items() if d < math.inf}


# --------------------------------------------------------------------------- #
# The algorithm on small hand-made worlds
# --------------------------------------------------------------------------- #

def test_cheaper_route_found_later_wins():
    # B is discovered first via the direct road (10), but A -> C -> B costs 3.
    # A node is final when it leaves the queue, not when it is first seen.
    result = uniform_cost_search(toy_world({("A", "B"): 10, ("A", "C"): 1, ("C", "B"): 2}), "A")
    assert result.time_to("B") == pytest.approx(3)
    assert result.path_to("B") == ["A", "C", "B"]


def test_source_costs_zero_and_its_path_is_itself():
    result = uniform_cost_search(toy_world({("A", "B"): 4}), "A")
    assert result.time_to("A") == 0
    assert result.path_to("A") == ["A"]


def test_unusable_road_is_never_used():
    result = uniform_cost_search(toy_world({("A", "B"): None, ("A", "C"): 1, ("C", "B"): 5}), "A")
    assert result.path_to("B") == ["A", "C", "B"]
    assert result.time_to("B") == pytest.approx(6)


def test_unreachable_nodes_are_missing():
    # D has no roads; A can only be left one way, so nothing leads back from B.
    result = uniform_cost_search(toy_world({("A", "B"): 1, ("C", "A"): 1}, extra_nodes=["D"]), "A")
    assert set(result.cost) == {"A", "B"}
    assert result.time_to("C") is None and result.path_to("C") is None
    assert result.time_to("D") is None and result.path_to("D") is None


def test_roads_are_directed():
    world = toy_world({("A", "B"): 1, ("B", "A"): 5})
    assert uniform_cost_search(world, "A").time_to("B") == pytest.approx(1)
    assert uniform_cost_search(world, "B").time_to("A") == pytest.approx(5)


def test_equal_cost_tie_is_broken_on_node_id():
    # Two routes to D of cost 2; the plan must be the same on every run.
    world = toy_world({("A", "C"): 1, ("A", "B"): 1, ("C", "D"): 1, ("B", "D"): 1})
    assert uniform_cost_search(world, "A").path_to("D") == ["A", "B", "D"]


def test_unknown_source_is_an_error():
    with pytest.raises(KeyError):
        uniform_cost_search(toy_world({("A", "B"): 1}), "X")


# --------------------------------------------------------------------------- #
# The scenarios
# --------------------------------------------------------------------------- #

def test_scenario1_routes_from_h1_by_hand():
    world = build_world(load_scenario(SCENARIOS / "Scenario1"))
    result = uniform_cost_search(world, "H1")
    # H1 -> N3 is unusable, so N3 is reached via N4: 12.6 + 57.5 s.
    assert world.cost("H1", "N3") is None
    assert result.path_to("N3") == ["H1", "N4", "N3"]
    assert result.time_to("N3") == pytest.approx(world.cost("H1", "N4") + world.cost("N4", "N3"))
    assert result.time_to("N3") == pytest.approx(70.1, abs=0.05)
    # H1 -> N2 directly (53.5) beats H1 -> N4 -> N2 (12.6 + 63.0).
    assert result.path_to("N2") == ["H1", "N2"]


def test_scenario2_halves_are_disconnected():
    s = load_scenario(SCENARIOS / "Scenario2")
    world = build_world(s)
    west = {"H1", "N1", "N3", "N4", "N5", "N6"}
    east = {"H2", "N2", "N7", "N8", "N9", "N10"}
    assert set(uniform_cost_search(world, "N1").cost) == west
    assert set(uniform_cost_search(world, "N2").cost) == east
    assert uniform_cost_search(world, "N1").path_to("N2") is None
    # With τ = 0.9 the N1 <-> N2 bridge is usable and the city is one piece again.
    lenient = build_world(s, WorldParams(blocked_threshold=0.9))
    assert set(uniform_cost_search(lenient, "N1").cost) == west | east


def test_scenario3_detour_around_blocked_n5_n16():
    world = build_world(load_scenario(SCENARIOS / "Scenario3"))
    there = uniform_cost_search(world, "N5")
    back = uniform_cost_search(world, "N16")
    assert there.path_to("N16") == ["N5", "N3", "N4", "N9", "N17", "N16"]
    assert back.path_to("N5") == ["N16", "N17", "N9", "N4", "N3", "N5"]
    # Same roads, other direction: each direction has its own traffic data.
    assert there.time_to("N16") != pytest.approx(back.time_to("N5"))
    assert len(there.cost) == 26  # one blocked road does not split this city


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_matches_bellman_ford_from_every_node(name):
    world = build_world(load_scenario(SCENARIOS / name))
    for source in world.graph.nodes:
        expected = bellman_ford(world, source)
        result = uniform_cost_search(world, source)
        assert result.cost.keys() == expected.keys()
        for node, dist in expected.items():
            assert result.time_to(node) == pytest.approx(dist)


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_every_path_is_drivable_and_adds_up(name):
    world = build_world(load_scenario(SCENARIOS / name))
    for source in world.graph.nodes:
        result = uniform_cost_search(world, source)
        for node in result.cost:
            path = result.path_to(node)
            assert path[0] == source and path[-1] == node
            costs = [world.cost(a, b) for a, b in zip(path, path[1:])]
            assert None not in costs  # only existing, usable roads
            assert sum(costs) == pytest.approx(result.time_to(node))


def test_travel_table_searches_each_distinct_source_once():
    s = load_scenario(SCENARIOS / "Scenario1")
    world = build_world(s)
    sources = [r.start_location for r in s.responders] + [i.location for i in s.incidents]
    table = travel_table(world, sources)
    assert list(table) == sorted(set(sources))
    for source, result in table.items():
        assert result.source == source
        assert result.cost == uniform_cost_search(world, source).cost
