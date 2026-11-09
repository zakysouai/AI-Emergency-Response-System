"""Tests for the allocation (emergency/allocation), step 3a: revise=False.

Small hand-made worlds check one rule of the CSP at a time; the scenarios
check the whole event loop: a hand-checked plan for Scenario 1, a brute-force
comparison for every event, validity of every assignment, and that the plan
never uses incidents before their timestamp.
"""

import dataclasses
import itertools
from pathlib import Path

import pytest

from emergency.allocation import ResponderState, schedule_chain, simulate, solve_event
from emergency.allocation.csp import _add, _chain_score
from emergency.data import Incident, Priority, Responder, ResponderType, load_scenario
from emergency.search import travel_table
from emergency.world import build_world
from tests.helpers import toy_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]
CRIT, HIGH = Priority.CRITICAL, Priority.HIGH


def incident(iid, location, priority=HIGH, deadline=1000.0, timestamp=0.0, time_required=0.0, capability="X"):
    return Incident(iid, location, priority, deadline, capability, timestamp, time_required)


def responder(rid, location, capabilities=("X",), available_from=0.0):
    return Responder(rid, ResponderType.AMBULANCE, location, frozenset(capabilities), available_from)


def solve(world, incidents, responders, now=0.0, node_limit=100_000):
    table = travel_table(world, world.graph.nodes)
    states = {r.id: ResponderState(r.available_from, r.start_location) for r in responders}
    return solve_event(now, incidents, responders, states, table, node_limit)


def ids(solution):
    return {rid: [inc.id for inc in chain] for rid, chain in solution.chains.items()}


# --------------------------------------------------------------------------- #
# Timing of a chain
# --------------------------------------------------------------------------- #

def test_schedule_chain_by_hand():
    world = toy_world({("A", "B"): 10, ("B", "C"): 5})
    chain = [incident("I1", "B", time_required=4), incident("I2", "C", time_required=2)]
    first, second = schedule_chain("R", ResponderState(3, "A"), chain, 0.0, travel_table(world, "ABC"))
    # Free at 3 -> leaves A at 3, arrives at B at 13, busy 4 s -> leaves B at 17, arrives at C at 22.
    assert (first.departure, first.arrival, first.finish, first.path) == (3, 13, 17, ("A", "B"))
    assert (second.departure, second.arrival, second.finish, second.path) == (17, 22, 24, ("B", "C"))


def test_responder_never_leaves_before_now():
    world = toy_world({("A", "B"): 10})
    [task] = schedule_chain("R", ResponderState(0, "A"), [incident("I", "B")], 50.0, travel_table(world, "AB"))
    assert task.departure == 50 and task.arrival == 60


def test_arriving_exactly_at_the_deadline_is_on_time():
    # The deadline is the latest time at which the responder must have arrived (assignment 3.2).
    world = toy_world({("A", "B"): 10})
    score, _ = _chain_score(ResponderState(0, "A"), [incident("I", "B", CRIT, deadline=10)], 0.0,
                            travel_table(world, "AB"))
    assert score[CRIT.rank] == 1


def test_unreachable_leg_gives_none():
    world = toy_world({("A", "B"): 1}, extra_nodes=["C"])
    assert schedule_chain("R", ResponderState(0, "A"), [incident("I", "C")], 0.0,
                          travel_table(world, "ABC")) is None


# --------------------------------------------------------------------------- #
# The CSP on hand-made worlds
# --------------------------------------------------------------------------- #

def test_only_capable_responders_are_used():
    world = toy_world({("A", "B"): 1, ("C", "B"): 50})
    responders = [responder("R1", "A", capabilities=["Y"]), responder("R2", "C")]
    assert ids(solve(world, [incident("I", "B")], responders)) == {"R2": ["I"]}


def test_split_that_saves_both_critical_deadlines():
    # Greedy would send R1 to I1 (arrival 1); then I2 can only get R2 (arrival 20, late).
    # The CSP sends R2 to I1 (4) and R1 to I2 (2): both on time.
    world = toy_world({("A", "X"): 1, ("A", "Y"): 2, ("B", "X"): 4, ("B", "Y"): 20})
    incidents = [incident("I1", "X", CRIT, deadline=5), incident("I2", "Y", CRIT, deadline=5)]
    responders = [responder("R1", "A"), responder("R2", "B")]
    assert ids(solve(world, incidents, responders)) == {"R1": ["I2"], "R2": ["I1"]}


WORLD_ONE_RESPONDER = {("A", "B"): 1, ("A", "C"): 10, ("B", "C"): 10, ("C", "B"): 10}


def test_critical_deadline_wins_over_high_but_high_is_still_handled():
    # Only one of the two can be on time: the Critical one must win.
    high = incident("H", "B", HIGH, deadline=5, time_required=5)
    crit = incident("C", "C", CRIT, deadline=12, time_required=5)
    solution = solve(toy_world(WORLD_ONE_RESPONDER), [high, crit], [responder("R", "A")])
    assert ids(solution) == {"R": ["C", "H"]}  # C arrives at 10, H at 10 + 5 + 10 = 25 (late)
    assert solution.unhandled == []


def test_lower_priority_goes_first_when_both_then_fit():
    # Critical is planned first, but High must be inserted *before* it:
    # H first: H at 1, C at 1 + 5 + 10 = 16 <= 40. C first would make H late (25 > 2).
    high = incident("H", "B", HIGH, deadline=2, time_required=5)
    crit = incident("C", "C", CRIT, deadline=40, time_required=5)
    assert ids(solve(toy_world(WORLD_ONE_RESPONDER), [high, crit], [responder("R", "A")])) == {"R": ["H", "C"]}


def test_impossible_incident_is_handled_after_the_feasible_one():
    on_time = incident("OK", "B", deadline=10)
    hopeless = incident("LATE", "C", deadline=0)
    solution = solve(toy_world(WORLD_ONE_RESPONDER), [hopeless, on_time], [responder("R", "A")])
    assert ids(solution) == {"R": ["OK", "LATE"]}  # LATE first would push OK to 20


def test_response_time_decides_when_deadlines_are_equal():
    world = toy_world({("A", "X"): 1, ("A", "Y"): 9, ("B", "X"): 9, ("B", "Y"): 2})
    incidents = [incident("I1", "X"), incident("I2", "Y")]
    assert ids(solve(world, incidents, [responder("R1", "A"), responder("R2", "B")])) == \
        {"R1": ["I1"], "R2": ["I2"]}


def test_unhandled_when_nobody_is_capable_or_nobody_can_reach_it():
    world = toy_world({("A", "B"): 1}, extra_nodes=["Z"])
    incidents = [incident("NOCAP", "B", capability="Y"), incident("NOROAD", "Z"), incident("OK", "B")]
    solution = solve(world, incidents, [responder("R", "A")])
    assert ids(solution) == {"R": ["OK"]}
    assert {inc.id for inc in solution.unhandled} == {"NOCAP", "NOROAD"}


def test_node_limit_still_returns_a_full_plan():
    world = toy_world({("A", "X"): 1, ("A", "Y"): 2, ("B", "X"): 4, ("B", "Y"): 20})
    incidents = [incident("I1", "X"), incident("I2", "Y")]
    solution = solve(world, incidents, [responder("R1", "A"), responder("R2", "B")], node_limit=1)
    assert not solution.complete
    assert sum(len(c) for c in solution.chains.values()) == 2 and solution.unhandled == []


# --------------------------------------------------------------------------- #
# The scenarios
# --------------------------------------------------------------------------- #

def brute_force_score(now, incidents, responders, states, table):
    """Every responder (or none) for every incident, every order per responder."""
    options = [[r.id for r in responders if r.can_handle(i.required_capability)] + [None] for i in incidents]
    best = None
    for choice in itertools.product(*options):
        groups = {}
        for inc, rid in zip(incidents, choice):
            if rid is not None:
                groups.setdefault(rid, []).append(inc)
        total = (0.0,) * (len(Priority) + 2)
        for rid, group in groups.items():
            scores = [s[0] for p in itertools.permutations(group)
                      if (s := _chain_score(states[rid], list(p), now, table))]
            if not scores:
                break
            total = _add(total, max(scores))
        else:
            best = total if best is None else max(best, total)
    return best


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_every_event_matches_brute_force(name):
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    table = travel_table(world, world.graph.nodes)
    states = {r.id: ResponderState(r.available_from, r.start_location) for r in s.responders}
    for now, group in itertools.groupby(s.incidents, key=lambda i: i.timestamp):
        incidents = list(group)
        solution = solve_event(now, incidents, s.responders, states, table)
        score = (0.0,) * (len(Priority) + 2)
        for rid, chain in solution.chains.items():
            score = _add(score, _chain_score(states[rid], chain, now, table)[0])
        assert score == pytest.approx(brute_force_score(now, incidents, s.responders, states, table))
        for rid, chain in solution.chains.items():  # revise=False: the chain stays fixed
            last = schedule_chain(rid, states[rid], chain, now, table)[-1]
            states[rid] = ResponderState(last.finish, last.path[-1])


def test_scenario1_plan_by_hand():
    s = load_scenario(SCENARIOS / "Scenario1")
    result = simulate(s, build_world(s))
    tasks = {a.incident_id: a for a in result.assignments}
    assert {(a.responder_id, i) for i, a in tasks.items()} == {
        ("R1", "I2"), ("R2", "I4"), ("R3", "I3"), ("R4", "I1"), ("R4", "I6"), ("R1", "I5"), ("R3", "I7")}
    # Both Critical deadlines are met: R2 (not R4) takes I4, so R4 takes I1 once free at 10.
    assert tasks["I4"].arrival == pytest.approx(53.5, abs=0.05)
    assert tasks["I1"].departure == 10 and tasks["I1"].arrival == pytest.approx(78.6, abs=0.05)
    # I6 (deadline 140): R4, free at 88.6 at N4, is the earliest arrival but still 0.7 s late.
    assert tasks["I6"].arrival == pytest.approx(140.7, abs=0.05)
    deadline = {i.id: i.deadline for i in s.incidents}
    assert sum(a.arrival <= deadline[i] for i, a in tasks.items()) == 5


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_every_assignment_is_valid(name, revise):
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    result = simulate(s, world, revise=revise)
    incidents = {i.id: i for i in s.incidents}
    handled = [a.incident_id for a in result.assignments]
    assert len(handled) == len(set(handled))  # nobody twice
    assert set(handled) | {i.id for i in result.unhandled} == set(incidents)
    for r in s.responders:
        free, location = r.available_from, r.start_location
        for a in sorted((a for a in result.assignments if a.responder_id == r.id), key=lambda a: a.departure):
            inc = incidents[a.incident_id]
            assert r.can_handle(inc.required_capability)
            assert a.departure >= max(free, inc.timestamp)  # one task at a time, nothing before it is known
            assert a.path[0] == location and a.path[-1] == inc.location
            costs = [world.cost(x, y) for x, y in zip(a.path, a.path[1:])]
            assert None not in costs and sum(costs) == pytest.approx(a.arrival - a.departure)
            assert a.finish == pytest.approx(a.arrival + inc.time_required)
            free, location = a.finish, inc.location


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_plan_never_uses_future_incidents(name):
    # Cutting off every incident after time t must not change any decision made up to t.
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    full = simulate(s, world).assignments
    for t in sorted({i.timestamp for i in s.incidents}):
        known = tuple(i for i in s.incidents if i.timestamp <= t)
        cut = simulate(dataclasses.replace(s, incidents=known), world).assignments
        assert set(cut) == {a for a in full if a.incident_id in {i.id for i in known}}


def test_simulation_reports_unhandled_incidents():
    # No responder in Scenario 1 has this capability; the rest of the plan must not change.
    s = load_scenario(SCENARIOS / "Scenario1")
    world = build_world(s)
    impossible = incident("IX", "N1", timestamp=50.0, capability="Bomb disposal")
    extended = dataclasses.replace(s, incidents=tuple(sorted(s.incidents + (impossible,),
                                                             key=lambda i: (i.timestamp, i.id))))
    result = simulate(extended, world)
    assert [i.id for i in result.unhandled] == ["IX"]
    assert result.assignments == simulate(s, world).assignments


def test_simulation_is_deterministic_and_warns_at_node_limit():
    s = load_scenario(SCENARIOS / "Scenario2")
    world = build_world(s)
    assert simulate(s, world) == simulate(s, world)
    limited = simulate(s, world, node_limit=1)
    assert limited.warnings and len(limited.assignments) == len(s.incidents)


# --------------------------------------------------------------------------- #
# Step 3b: revise=True (tasks that have not departed are planned again)
# --------------------------------------------------------------------------- #

def test_revise_puts_a_new_incident_before_a_waiting_task():
    # R is busy until 10. At t=0 it gets C1 (leaves at 10). At t=5, H appears next to it.
    # A: H after C1 -> H at 35 (late). B: C1 has not left yet, so H first (11), then C1 (26).
    world = toy_world(WORLD_ONE_RESPONDER)
    c1 = incident("C1", "C", CRIT, deadline=40, time_required=5)
    h = incident("H", "B", HIGH, deadline=15, timestamp=5.0, time_required=5)
    s = dataclasses.replace(load_scenario(SCENARIOS / "Scenario1"),
                            responders=(responder("R", "A", available_from=10.0),), incidents=(c1, h))
    order = {revise: [(a.incident_id, a.arrival) for a in simulate(s, world, revise=revise).assignments]
             for revise in (False, True)}
    assert order[False] == [("C1", 20), ("H", 35)]
    assert order[True] == [("H", 11), ("C1", 26)]


def _rounded(score):
    return tuple(round(x, 6) for x in score)


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_revise_is_never_worse_than_keeping_the_old_plan_at_any_event(name):
    # At every event, "keep the waiting tasks and put the new incidents after them"
    # (what A would do from the same state) is one of the options B searches,
    # so B's score for that event can never be lower.
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    table = travel_table(world, world.graph.nodes)
    incidents = {i.id: i for i in s.incidents}
    plans = {r.id: [] for r in s.responders}
    for now, group in itertools.groupby(s.incidents, key=lambda i: i.timestamp):
        new, waiting, states = list(group), {}, {}
        for r in s.responders:
            waiting[r.id] = [incidents[a.incident_id] for a in plans[r.id] if a.departure > now]
            plans[r.id] = [a for a in plans[r.id] if a.departure <= now]
            last = plans[r.id][-1] if plans[r.id] else None
            states[r.id] = ResponderState(last.finish, last.path[-1]) if last \
                else ResponderState(r.available_from, r.start_location)

        revised = solve_event(now, new + sum(waiting.values(), []), s.responders, states, table)
        score_b = (0.0,) * (len(Priority) + 2)
        for rid, chain in revised.chains.items():
            score_b = _add(score_b, _chain_score(states[rid], chain, now, table)[0])

        score_a, after_waiting = (0.0,) * (len(Priority) + 2), dict(states)
        for rid, chain in waiting.items():
            if chain:
                score_a = _add(score_a, _chain_score(states[rid], chain, now, table)[0])
                last = schedule_chain(rid, states[rid], chain, now, table)[-1]
                after_waiting[rid] = ResponderState(last.finish, last.path[-1])
        for rid, chain in solve_event(now, new, s.responders, after_waiting, table).chains.items():
            score_a = _add(score_a, _chain_score(after_waiting[rid], chain, now, table)[0])

        assert _rounded(score_b) >= _rounded(score_a)
        for rid, chain in revised.chains.items():
            plans[rid] += schedule_chain(rid, states[rid], chain, now, table)


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_revise_never_changes_a_task_that_has_departed(name):
    # A responder on its way is never called back, and departed tasks never depend on the future.
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    full = set(simulate(s, world, revise=True).assignments)
    for t in sorted({i.timestamp for i in s.incidents}):
        known = tuple(i for i in s.incidents if i.timestamp <= t)
        cut = simulate(dataclasses.replace(s, incidents=known), world, revise=True).assignments
        assert {a for a in cut if a.departure <= t} <= full
