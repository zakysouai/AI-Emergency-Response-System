"""Tests for statistics.txt (emergency/plan/statistics.py) and the entry point run.py.

The statistics are checked on hand-made assignments for the Scenario 1
incidents, so each definition of choice 12 is tested on its own:

    I1 High 0..80   I2 Critical 0..90   I3 High 0..150   I4 Critical 0..60
    I5 High 50..200 I6 High 50..140     I7 High 60..200   (timestamp..deadline)

run.py is called through main() with the output in a temporary folder.
"""

import json
from pathlib import Path

import pytest

import run
from emergency.allocation import Assignment, SimulationResult, simulate
from emergency.data import Priority, load_scenario
from emergency.plan import Issue, ValidationReport, compute_statistics, format_statistics, validate_plan
from emergency.world import build_world

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"


@pytest.fixture(scope="module")
def s1():
    return load_scenario(SCENARIOS / "Scenario1")


def task(responder_id, incident_id, arrival):
    # Only responder, incident and arrival matter for the statistics.
    return Assignment(responder_id, incident_id, ("N1",), 0.0, arrival, arrival + 10)


# --------------------------------------------------------------------------- #
# compute_statistics
# --------------------------------------------------------------------------- #

def test_statistics_by_hand(s1):
    tasks = [task("R1", "I1", 70), task("R1", "I2", 90), task("R2", "I3", 160), task("R2", "I5", 100)]
    stats = compute_statistics(s1, tasks)
    assert (stats.incidents, stats.handled, stats.responders, stats.responders_used) == (7, 4, 4, 2)
    # Response times 70, 90, 160 and 100 - 50 = 50 (I5 is only known at 50).
    assert stats.average_response == pytest.approx((70 + 90 + 160 + 50) / 4)
    # On time: I1, I2 (exactly at the deadline) and I5. I3 is late.
    assert stats.met == 3 and stats.met_percentage == pytest.approx(300 / 7)
    assert stats.late == (("I3", 160, 150),)
    assert stats.unhandled == ("I4", "I6", "I7")


def test_unhandled_counts_as_missed_but_not_in_the_response_time(s1):
    stats = compute_statistics(s1, [task("R1", "I1", 10)])
    assert stats.average_response == 10  # only I1 is averaged
    assert stats.met_percentage == pytest.approx(100 / 7)  # but divided by all 7 incidents
    assert stats.late == ()  # unhandled is not "late"


def test_arriving_exactly_at_the_deadline_is_met(s1):
    assert compute_statistics(s1, [task("R1", "I4", 60)]).met == 1
    assert compute_statistics(s1, [task("R1", "I4", 60.001)]).met == 0


def test_deadlines_per_priority(s1):
    stats = compute_statistics(s1, [task("R1", "I2", 50), task("R1", "I4", 61), task("R2", "I1", 1)])
    assert stats.met_by_priority == {Priority.CRITICAL: (1, 2), Priority.HIGH: (1, 5)}  # no Medium/Low in S1


def test_nothing_handled(s1):
    stats = compute_statistics(s1, [])
    assert (stats.handled, stats.responders_used, stats.met) == (0, 0, 0)
    assert stats.average_response is None and stats.met_percentage == 0
    assert "Average response time : n/a" in format_statistics(stats, "S", {}, ValidationReport((), ()))


def test_scenario1_plan(s1):
    # The plan of test_plan.py: response times 87.5, 53.5, 124.6, 78.6, 90.7, 146.1, 170.7.
    stats = compute_statistics(s1, simulate(s1, build_world(s1), revise=True).assignments)
    assert (stats.handled, stats.responders_used, stats.met) == (7, 4, 5)
    assert stats.average_response == pytest.approx(107.37, abs=0.01)
    assert [late[0] for late in stats.late] == ["I6", "I7"]


# --------------------------------------------------------------------------- #
# format_statistics
# --------------------------------------------------------------------------- #

def test_text_starts_with_the_block_of_the_assignment(s1):
    stats = compute_statistics(s1, [task("R1", "I1", 70), task("R2", "I2", 95)])
    text = format_statistics(stats, "Scenario1", {"tau": 0.5}, ValidationReport((), ()))
    assert text.splitlines()[:5] == [
        "System statistics :",
        " * 2 incidents handled",
        " * 2 responders used",
        " * Average response time : 82.5 s",
        " * Deadlines met : 14.3%",
    ]
    assert "Settings: tau = 0.5" in text and "seconds" in text


def test_text_lists_errors_but_not_the_late_warnings_twice(s1):
    stats = compute_statistics(s1, [task("R1", "I3", 160)])
    report = ValidationReport((Issue("C1", "incident I1 is not handled"),),
                              (Issue("W1", "late I3"), Issue("W3", "slow route")))
    text = format_statistics(stats, "Scenario1", {}, report)
    assert "INVALID (1 errors, 2 warnings)" in text
    assert "error C1: incident I1 is not handled" in text and "warning W3: slow route" in text
    assert "W1" not in text and " * I3: arrives at 160.0 s, deadline 150 s" in text


# --------------------------------------------------------------------------- #
# run.py
# --------------------------------------------------------------------------- #

def test_run_writes_a_valid_plan_and_statistics(tmp_path):
    assert run.main(["--out", str(tmp_path)]) == 0  # default: Scenario1
    s = load_scenario(SCENARIOS / "Scenario1")
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert validate_plan(plan, s, build_world(s)).valid and len(plan) == 7
    text = (tmp_path / "statistics.txt").read_text()
    assert " * Deadlines met : 71.4%" in text and "revise = True" in text


@pytest.mark.parametrize("args, line", [
    (["Scenario3"], " * Deadlines met : 55.0%"),
    (["Scenario3", "--no-revise"], " * Deadlines met : 50.0%"),
    (["Scenario2", "--tau", "0"], " * 1 incidents handled"),  # almost every road counts as blocked
])
def test_run_options(tmp_path, args, line):
    assert run.main(args + ["--out", str(tmp_path / "out")]) == 0  # --out folder is created
    assert line in (tmp_path / "out" / "statistics.txt").read_text().splitlines()


def test_bare_name_means_the_folder_in_scenarios(tmp_path, monkeypatch):
    (tmp_path / "Scenario2").mkdir()  # e.g. old output with the same name
    monkeypatch.chdir(tmp_path)
    assert run.main(["Scenario2"]) == 0
    assert "Scenario: Scenario2 (12 incidents" in (tmp_path / "statistics.txt").read_text()


def test_path_to_a_scenario_folder(tmp_path):
    assert run.main([str(SCENARIOS / "Scenario2"), "--out", str(tmp_path)]) == 0


def test_missing_scenario_gives_exit_code_2(tmp_path, capsys):
    assert run.main([str(tmp_path / "nothing"), "--out", str(tmp_path)]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize("tau", ["-0.1", "1.5", "abc"])
def test_bad_tau_is_a_usage_error(tau):
    with pytest.raises(SystemExit) as exc:
        run.main(["--tau", tau])
    assert exc.value.code == 2


def test_invalid_plan_gives_exit_code_1(tmp_path, monkeypatch):
    real = run.simulate

    def drops_one_incident(*args, **kwargs):
        result = real(*args, **kwargs)
        return SimulationResult(result.assignments[1:], result.unhandled, result.warnings)

    monkeypatch.setattr(run, "simulate", drops_one_incident)
    assert run.main(["--out", str(tmp_path)]) == 1
    # statistics.txt is still written, with the reason.
    assert "INVALID" in (tmp_path / "statistics.txt").read_text()
    assert "error C1" in (tmp_path / "statistics.txt").read_text()
