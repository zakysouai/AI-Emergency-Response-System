"""Tests for the data layer (emergency/data)."""

import json
import shutil
from pathlib import Path

import pytest

from emergency.data import (
    DataError,
    Priority,
    ReportSource,
    ResponderType,
    RoadStatus,
    TrafficLevel,
    Weather,
    load_scenario,
)

SCENARIOS = Path(__file__).resolve().parent.parent / "Scenarios"
ALL_SCENARIOS = ["Scenario1", "Scenario2", "Scenario3"]


# --------------------------------------------------------------------------- #
# The provided scenarios load correctly
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name, nodes, roads, responders, incidents, reported_roads, traffic_roads",
    [
        ("Scenario1", 5, 14, 4, 7, 6, 14),
        ("Scenario2", 12, 30, 10, 12, 14, 3),
        ("Scenario3", 26, 60, 10, 20, 14, 10),
    ],
)
def test_scenario_counts(name, nodes, roads, responders, incidents, reported_roads, traffic_roads):
    s = load_scenario(SCENARIOS / name)
    assert s.name == name
    assert len(s.graph.nodes) == nodes
    assert len(s.graph.roads) == roads
    assert len(s.responders) == responders
    assert len(s.incidents) == incidents
    assert len(s.road_evidence) == reported_roads
    assert len(s.traffic_observations) == traffic_roads
    assert s.warnings == ()


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_incidents_sorted_by_timestamp(name):
    times = [inc.timestamp for inc in load_scenario(SCENARIOS / name).incidents]
    assert times == sorted(times)


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_every_road_is_at_least_as_long_as_straight_line(name):
    # Needed for the A* heuristic (euclidean / max speed) to be admissible.
    graph = load_scenario(SCENARIOS / name).graph
    for road in graph.roads.values():
        assert road.distance >= graph.euclidean(road.from_node, road.to_node)


def test_scenario1_graph_details():
    graph = load_scenario(SCENARIOS / "Scenario1").graph
    road = graph.road("H1", "N1")
    assert road.distance == 458 and road.speed == 15 and road.road_type == "secondary"
    assert road.base_time == pytest.approx(458 / 15)
    assert graph.nodes["H1"].type == "hospital"
    assert {r.to_node for r in graph.outgoing("N1")} == {"H1", "N2"}
    assert graph.road("N1", "N3") is None
    assert graph.max_speed == 30


def test_scenario1_responders():
    responders = {r.id: r for r in load_scenario(SCENARIOS / "Scenario1").responders}
    assert responders["R1"].type is ResponderType.FIRE_TRUCK
    assert responders["R1"].capabilities == {"Fire suppression", "Rescue"}
    assert responders["R1"].can_handle("Rescue")
    assert not responders["R1"].can_handle("First aid")
    assert responders["R1"].available_from == 0
    # R4 starts Busy for 10 s.
    assert responders["R4"].available_from == 10


def test_scenario1_incidents():
    incidents = {i.id: i for i in load_scenario(SCENARIOS / "Scenario1").incidents}
    i5 = incidents["I5"]
    assert i5.location == "N1"
    assert i5.priority is Priority.HIGH
    assert (i5.timestamp, i5.deadline, i5.time_required) == (50, 200, 20)
    assert Priority.CRITICAL.rank < Priority.HIGH.rank < Priority.MEDIUM.rank < Priority.LOW.rank


def test_scenario1_road_reports_are_directed():
    evidence = load_scenario(SCENARIOS / "Scenario1").road_evidence
    forward, backward = evidence[("N1", "N2")], evidence[("N2", "N1")]
    assert forward.weather is Weather.RAIN
    assert [(r.source, r.reported_status) for r in forward.reports] == [
        (ReportSource.CITIZEN, RoadStatus.BLOCKED),
        (ReportSource.POLICE, RoadStatus.BLOCKED),
        (ReportSource.SENSOR, RoadStatus.CONGESTED),
    ]
    assert {r.reported_status for r in backward.reports} == {RoadStatus.CONGESTED}
    assert evidence[("H1", "N3")].weather is Weather.STORM
    assert ("H1", "N1") not in evidence  # unreported roads are simply absent


def test_cpts_and_hmm_values():
    s = load_scenario(SCENARIOS / "Scenario1")
    assert s.road_cpts.weather_prior[Weather.STORM] == 0.20
    assert s.road_cpts.status_given_weather[Weather.STORM][RoadStatus.BLOCKED] == 0.50
    assert s.road_cpts.report_given_status[ReportSource.POLICE][RoadStatus.BLOCKED][RoadStatus.BLOCKED] == 0.90
    assert s.hmm.initial[TrafficLevel.LOW] == 0.60
    assert s.hmm.transition[TrafficLevel.HIGH][TrafficLevel.HIGH] == 0.75
    assert s.hmm.emission[TrafficLevel.LOW][TrafficLevel.LOW] == 0.85


def test_hmm_parameters_differ_per_scenario():
    # The HMM must be loaded per scenario, not hard-coded.
    a = load_scenario(SCENARIOS / "Scenario1").hmm
    b = load_scenario(SCENARIOS / "Scenario2").hmm
    assert a.initial[TrafficLevel.LOW] != b.initial[TrafficLevel.LOW]


def test_traffic_sequence_is_ordered_by_observation_nr():
    obs = load_scenario(SCENARIOS / "Scenario1").traffic_observations[("H1", "N1")]
    assert len(obs) == 10
    assert obs[:4] == (TrafficLevel.LOW, TrafficLevel.LOW, TrafficLevel.LOW, TrafficLevel.MEDIUM)


# --------------------------------------------------------------------------- #
# Broken input is rejected or flagged
# --------------------------------------------------------------------------- #

@pytest.fixture
def scenario_copy(tmp_path):
    """A writable copy of Scenario1 that a test can corrupt."""
    target = tmp_path / "Scenario1"
    shutil.copytree(SCENARIOS / "Scenario1", target)
    return target


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not found in {path.name}"
    path.write_text(text.replace(old, new, 1))


def _append_row(path: Path, row: str) -> None:
    # The provided CSV files do not end with a newline.
    text = path.read_text()
    path.write_text(text + ("" if text.endswith("\n") else "\n") + row + "\n")


def _edit_json(path: Path, edit) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def test_missing_folder():
    with pytest.raises(DataError, match="does not exist"):
        load_scenario(SCENARIOS / "NoSuchScenario")


def test_missing_file(scenario_copy):
    (scenario_copy / "incidents.csv").unlink()
    with pytest.raises(DataError, match="missing input file incidents.csv"):
        load_scenario(scenario_copy)


def test_road_to_unknown_node(scenario_copy):
    _edit_json(scenario_copy / "city_graph.json", lambda g: g["roads"][0].update(to="X9"))
    with pytest.raises(DataError, match="unknown node 'X9'"):
        load_scenario(scenario_copy)


def test_duplicate_road(scenario_copy):
    _edit_json(scenario_copy / "city_graph.json", lambda g: g["roads"].append(dict(g["roads"][0])))
    with pytest.raises(DataError, match="duplicate road"):
        load_scenario(scenario_copy)


def test_non_positive_speed(scenario_copy):
    _edit_json(scenario_copy / "city_graph.json", lambda g: g["roads"][0].update(speed=0))
    with pytest.raises(DataError, match="must be > 0"):
        load_scenario(scenario_copy)


def test_responder_at_unknown_node(scenario_copy):
    _replace(scenario_copy / "responders.csv", "R1,FireTruck,N1", "R1,FireTruck,N99")
    with pytest.raises(DataError, match=r"responders.csv:2: unknown node 'N99'"):
        load_scenario(scenario_copy)


def test_unknown_responder_type(scenario_copy):
    _replace(scenario_copy / "responders.csv", "R1,FireTruck", "R1,Helicopter")
    with pytest.raises(DataError, match="not a valid ResponderType"):
        load_scenario(scenario_copy)


def test_unknown_priority(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "I1,N4,High", "I1,N4,Urgent")
    with pytest.raises(DataError, match="not a valid Priority"):
        load_scenario(scenario_copy)


def test_duplicate_incident(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "I2,", "I1,")
    with pytest.raises(DataError, match="duplicate incident id 'I1'"):
        load_scenario(scenario_copy)


def test_non_numeric_deadline(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "I1,N4,High,80", "I1,N4,High,soon")
    with pytest.raises(DataError, match="deadline='soon' is not a number"):
        load_scenario(scenario_copy)


def test_report_for_missing_road(scenario_copy):
    _append_row(scenario_copy / "road_reports.csv", "N1,N3,Rain,Police,Open")
    with pytest.raises(DataError, match="road N1->N3 does not exist"):
        load_scenario(scenario_copy)


def test_conflicting_weather_on_one_road(scenario_copy):
    _replace(scenario_copy / "road_reports.csv", "N1,N2,Rain,Police", "N1,N2,Storm,Police")
    with pytest.raises(DataError, match="conflicting weather"):
        load_scenario(scenario_copy)


def test_probabilities_must_sum_to_one(scenario_copy):
    _edit_json(scenario_copy / "road_probabilities.json",
               lambda d: d["police_report"]["Open"].update(Open=0.5))
    with pytest.raises(DataError, match=r"police_report\[Open\]: probabilities sum to"):
        load_scenario(scenario_copy)


def test_missing_cpt_row(scenario_copy):
    _edit_json(scenario_copy / "traffic_probabilities.json", lambda d: d["transition"].pop("High"))
    with pytest.raises(DataError, match="missing rows for \\['High'\\]"):
        load_scenario(scenario_copy)


def test_duplicate_observation_nr(scenario_copy):
    _append_row(scenario_copy / "observed_traffic.csv", "1,H1,N1,High")
    with pytest.raises(DataError, match="duplicate observation_nr 1"):
        load_scenario(scenario_copy)


def test_row_with_too_many_fields(scenario_copy):
    _append_row(scenario_copy / "road_reports.csv", "N1,N2,Rain,Police,Open,extra")
    with pytest.raises(DataError, match="more fields than columns"):
        load_scenario(scenario_copy)


def _reverse_data_rows(path: Path) -> None:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    path.write_text("\n".join([lines[0]] + lines[:0:-1]) + "\n")


def test_incidents_sorted_even_if_file_is_not(scenario_copy):
    # The provided files are already in order, so shuffle them to test the sorting.
    _reverse_data_rows(scenario_copy / "incidents.csv")
    incidents = load_scenario(scenario_copy).incidents
    assert [(i.timestamp, i.id) for i in incidents] == sorted((i.timestamp, i.id) for i in incidents)
    assert incidents[0].id == "I1"


def test_traffic_ordered_even_if_file_is_not(scenario_copy):
    original = load_scenario(scenario_copy).traffic_observations
    _reverse_data_rows(scenario_copy / "observed_traffic.csv")
    assert load_scenario(scenario_copy).traffic_observations == original


def test_negative_time_required(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "Medical emergency,0,10", "Medical emergency,0,-10")
    with pytest.raises(DataError, match="time_required=-10.0 must be >= 0"):
        load_scenario(scenario_copy)


def test_empty_required_capability(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "I1,N4,High,80,Medical emergency", "I1,N4,High,80,")
    with pytest.raises(DataError, match="no required capability"):
        load_scenario(scenario_copy)


def test_impossible_deadline_is_a_warning(scenario_copy):
    # I5 appears at t=50; a deadline of 40 cannot be met but is not malformed.
    _replace(scenario_copy / "incidents.csv", "I5,N1,High,200", "I5,N1,High,40")
    s = load_scenario(scenario_copy)
    assert any("I5" in w and "never be met" in w for w in s.warnings)


def test_uncovered_capability_is_a_warning(scenario_copy):
    _replace(scenario_copy / "incidents.csv", "Medical emergency", "Bomb disposal")
    s = load_scenario(scenario_copy)
    assert any("Bomb disposal" in w for w in s.warnings)
