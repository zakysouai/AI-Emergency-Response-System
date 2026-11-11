"""Tests for plan.json and the plan validator (emergency/plan).

The generated plans must be valid. Then a valid plan for Scenario 1 is damaged
in one way at a time, and the validator must report exactly the expected
error codes. The plan being damaged (revise=True, expected travel times):

    R1 -> I2  N1 H1 N2      t=0       R1 -> I5  N2 N1        t=117.5
    R2 -> I4  H1 N2         t=0
    R3 -> I3  N2 H1 N4 N3   t=0       R3 -> I7  N3 N4 H1     t=144.6
    R4 -> I1  N3 N4         t=10      R4 -> I6  N4 H1 N1     t=88.6
"""

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from emergency.allocation import simulate
from emergency.data import Incident, Priority, load_scenario
from emergency.plan import plan_entries, validate_plan, validate_plan_text, write_plan
from emergency.world import build_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]


@pytest.fixture(scope="module")
def s1():
    s = load_scenario(SCENARIOS / "Scenario1")
    world = build_world(s)
    return s, world, plan_entries(simulate(s, world, revise=True).assignments)


def error_codes(report):
    return {issue.code for issue in report.errors}


def warning_codes(report):
    return {issue.code for issue in report.warnings}


# --------------------------------------------------------------------------- #
# plan.json and the generated plans
# --------------------------------------------------------------------------- #

def test_plan_json_has_exactly_the_required_format(s1, tmp_path):
    s, world, entries = s1
    write_plan(tmp_path / "plan.json", simulate(s, world, revise=True).assignments)
    data = json.loads((tmp_path / "plan.json").read_text())
    assert data == entries
    assert all(list(e) == ["responder_id", "incident_id", "path", "time"] for e in data)
    assert data[0] == {"responder_id": "R1", "incident_id": "I2", "path": ["N1", "H1", "N2"], "time": 0.0}


def test_baseline_plan_matches_the_docstring(s1):
    _, _, entries = s1
    by_incident = {e["incident_id"]: e for e in entries}
    assert by_incident["I7"]["path"] == ["N3", "N4", "H1"]
    assert by_incident["I6"]["time"] == pytest.approx(88.6, abs=0.05)
    assert by_incident["I5"]["time"] == pytest.approx(117.5, abs=0.05)


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_generated_plans_are_valid(name, revise):
    s = load_scenario(SCENARIOS / name)
    world = build_world(s)
    assignments = simulate(s, world, revise=revise).assignments
    report = validate_plan_text(json.dumps(plan_entries(assignments)), s, world)
    assert report.errors == ()
    # The only warnings are the missed deadlines, one per late incident.
    deadline = {i.id: i.deadline for i in s.incidents}
    late = sum(a.arrival > deadline[a.incident_id] for a in assignments)
    assert [w.code for w in report.warnings] == ["W1"] * late


# --------------------------------------------------------------------------- #
# One damage at a time -> exactly the expected error codes
# --------------------------------------------------------------------------- #

def _edit(target, **changes):
    def damage(entries, scenario):
        for entry in entries:
            if entry["incident_id"] == target:
                entry.update(changes)
        return entries
    return damage


def _transform(incident_id, function):
    def damage(entries, scenario):
        return [function(e) if e["incident_id"] == incident_id else e for e in entries]
    return damage


def _drop(incident_id):
    return lambda entries, scenario: [e for e in entries if e["incident_id"] != incident_id]


def _duplicate(incident_id):
    return lambda entries, scenario: entries + [copy.deepcopy(e) for e in entries if e["incident_id"] == incident_id]


# Damage on I7 (the last task of R3) also leaves I7 unhandled -> C1.
DAMAGES = {
    "not a list": (lambda entries, scenario: {"plan": entries}, {"S1"}),
    "entry is a string": (_transform("I7", lambda e: "I7"), {"S2", "C1"}),
    "extra key": (_edit("I7", arrival=200.0), {"S2", "C1"}),
    "missing key": (_transform("I7", lambda e: {k: v for k, v in e.items() if k != "time"}), {"S2", "C1"}),
    "time is a bool": (_edit("I7", time=True), {"S3", "C1"}),
    "time is NaN": (_edit("I7", time=float("nan")), {"S3", "C1"}),
    "time is infinite": (_edit("I7", time=float("inf")), {"S3", "C1"}),
    "negative time": (_edit("I7", time=-1), {"S3", "C1"}),
    "path is a string": (_edit("I7", path="N3"), {"S3", "C1"}),
    "empty path": (_edit("I7", path=[]), {"S3", "C1"}),
    "responder id not a string": (_edit("I7", responder_id=3), {"S3", "C1"}),
    "unknown responder": (_edit("I7", responder_id="R99"), {"R1", "C1"}),
    "unknown incident": (_edit("I7", incident_id="I99"), {"R2", "C1"}),
    # The copy starts where the original ended (P5) and at the same time (T4).
    "incident twice": (_duplicate("I7"), {"R3", "P5", "T4"}),
    "missing capability": (_edit("I5", responder_id="R2"), {"R4"}),  # ambulance R2 is at N2, free at 63.5
    "unknown node": (_edit("I7", path=["N3", "X99", "N4", "H1"]), {"P1"}),
    "road does not exist": (_edit("I2", path=["N1", "N3", "H1", "N2"]), {"P2"}),
    "blocked road": (_edit("I2", path=["N1", "N2"]), {"P3"}),  # P(Blocked) of N1->N2 is 0.527 > 0.5
    "path ends elsewhere": (_edit("I7", path=["N3", "N4"]), {"P4"}),
    "path starts elsewhere": (_edit("I7", path=["N4", "H1"]), {"P5"}),
    "before the incident is known": (_edit("I6", time=40.0), {"T1", "T3"}),  # R4 is also still busy
    "before the responder is available": (_edit("I1", time=5.0), {"T2"}),
    "before the previous task is done": (_edit("I6", time=80.0), {"T3"}),
    "same start as previous task": (_edit("I6", time=10.0), {"T4", "T1"}),
    "incident left out": (_drop("I7"), {"C1"}),
}


@pytest.mark.parametrize("damage, expected", DAMAGES.values(), ids=DAMAGES.keys())
def test_each_damage_gives_exactly_the_expected_errors(s1, damage, expected):
    s, world, entries = s1
    assert validate_plan(entries, s, world).errors == ()  # the undamaged plan
    report = validate_plan(damage(copy.deepcopy(entries), s), s, world)
    assert error_codes(report) == expected


def test_order_of_entries_in_the_file_does_not_matter(s1):
    # Each responder's tasks are replayed in order of start time, not in file order.
    s, world, entries = s1
    assert validate_plan(entries[::-1], s, world).valid


def test_invalid_json_text(s1):
    s, world, _ = s1
    assert error_codes(validate_plan_text("[{", s, world)) == {"S1"}


# --------------------------------------------------------------------------- #
# Warnings: the plan stays valid
# --------------------------------------------------------------------------- #

def test_missed_deadline_is_only_a_warning(s1):
    s, world, entries = s1
    report = validate_plan(entries, s, world)
    assert report.valid and warning_codes(report) == {"W1"}
    late = [w.message for w in report.warnings]
    assert len(late) == 2 and any("-> I6)" in m for m in late) and any("-> I7)" in m for m in late)


def test_incident_nobody_can_handle_is_only_a_warning(s1):
    s, world, entries = s1
    impossible = Incident("IX", "N1", Priority.LOW, 1000.0, "Bomb disposal", 50.0, 10.0)
    extended = dataclasses.replace(s, incidents=s.incidents + (impossible,))
    report = validate_plan(entries, extended, world)
    assert report.valid and "W2" in warning_codes(report)


def test_slower_route_is_only_a_warning(s1):
    s, world, entries = s1
    report = validate_plan(_edit("I5", path=["N2", "H1", "N1"])(copy.deepcopy(entries), s), s, world)
    assert report.valid and "W3" in warning_codes(report)  # 54.5 + 34.6 s instead of 78.6 s


def test_waiting_for_no_reason_is_only_a_warning(s1):
    s, world, entries = s1
    report = validate_plan(_edit("I5", time=118.0)(copy.deepcopy(entries), s), s, world)
    assert report.valid and "W4" in warning_codes(report)  # R1 is free at 117.5; 118 is no event
