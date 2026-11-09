"""Read a scenario folder into the objects of `models.py`.

Structural problems (missing columns, unknown nodes, probabilities that do not
sum to 1, ...) raise `DataError` immediately with the file and line involved.
Data that is valid but suspicious (e.g. a deadline before the incident's own
timestamp) is collected in `Scenario.warnings` instead, so the planner can
still run and report on it.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, TypeVar

from .models import (
    Edge,
    Graph,
    HMMParams,
    Incident,
    Node,
    Priority,
    ReportSource,
    Responder,
    ResponderType,
    Road,
    RoadCPTs,
    RoadEvidence,
    RoadReport,
    RoadStatus,
    Scenario,
    TrafficLevel,
    Weather,
)

PROBABILITY_TOLERANCE = 1e-6

# Key in road_probabilities.json holding each source's P(Reported | Status).
_REPORT_CPT_KEYS = {
    ReportSource.CITIZEN: "citizen_report",
    ReportSource.POLICE: "police_report",
    ReportSource.SENSOR: "sensor_report",
}

E = TypeVar("E", bound=Enum)


class DataError(ValueError):
    """Raised when a scenario file is malformed or inconsistent."""


# --------------------------------------------------------------------------- #
# Small parsing helpers
# --------------------------------------------------------------------------- #

def _read_csv(path: Path, required: list[str]) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (location, row) per non-blank row, with keys and values stripped."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [col for col in required if col not in header]
        if missing:
            raise DataError(f"{path.name}: missing column(s) {missing}")
        for raw in reader:
            if None in raw:  # DictReader puts surplus fields under the key None
                raise DataError(f"{path.name}:{reader.line_num}: more fields than columns in the header")
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if not any(row.values()):
                continue  # blank separator lines occur in the provided files
            yield f"{path.name}:{reader.line_num}", row


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            raise DataError(f"{path.name}: invalid JSON ({exc})") from exc


def _parse_float(value: Any, where: str, field: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DataError(f"{where}: {field}={value!r} is not a number") from None
    if not math.isfinite(number):
        raise DataError(f"{where}: {field}={value!r} is not finite")
    if minimum is not None and number < minimum:
        raise DataError(f"{where}: {field}={number} must be >= {minimum}")
    return number


def _parse_enum(enum_cls: type[E], value: str, where: str) -> E:
    try:
        return enum_cls(value)
    except ValueError:
        allowed = [member.value for member in enum_cls]
        raise DataError(f"{where}: {value!r} is not a valid {enum_cls.__name__} {allowed}") from None


def _require_node(graph: Graph, node_id: str, where: str) -> None:
    if node_id not in graph.nodes:
        raise DataError(f"{where}: unknown node {node_id!r}")


def _require_road(graph: Graph, edge: Edge, where: str) -> None:
    if edge not in graph.roads:
        raise DataError(f"{where}: road {edge[0]}->{edge[1]} does not exist in the graph")


def _parse_distribution(raw: Any, enum_cls: type[E], where: str) -> dict[E, float]:
    """A probability distribution over every member of `enum_cls`, summing to 1."""
    if not isinstance(raw, dict):
        raise DataError(f"{where}: expected an object, got {type(raw).__name__}")
    dist = {_parse_enum(enum_cls, key, where): _parse_float(p, where, key, 0.0) for key, p in raw.items()}
    missing = [m.value for m in enum_cls if m not in dist]
    if missing:
        raise DataError(f"{where}: missing probabilities for {missing}")
    total = sum(dist.values())
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        raise DataError(f"{where}: probabilities sum to {total}, not 1")
    return dist


def _parse_conditional(raw: Any, given: type[Enum], over: type[E], where: str) -> dict:
    """A table P(over | given): one distribution over `over` per value of `given`."""
    if not isinstance(raw, dict):
        raise DataError(f"{where}: expected an object, got {type(raw).__name__}")
    table = {
        _parse_enum(given, key, where): _parse_distribution(row, over, f"{where}[{key}]")
        for key, row in raw.items()
    }
    missing = [m.value for m in given if m not in table]
    if missing:
        raise DataError(f"{where}: missing rows for {missing}")
    return table


def _section(data: dict, key: str, where: str) -> Any:
    if key not in data:
        raise DataError(f"{where}: missing key {key!r}")
    return data[key]


# --------------------------------------------------------------------------- #
# Per-file loaders
# --------------------------------------------------------------------------- #

def load_graph(path: Path) -> Graph:
    data = _read_json(path)
    nodes: dict[str, Node] = {}
    for i, raw in enumerate(_section(data, "nodes", path.name)):
        where = f"{path.name}: nodes[{i}]"
        node_id = str(_section(raw, "id", where))
        if node_id in nodes:
            raise DataError(f"{where}: duplicate node id {node_id!r}")
        nodes[node_id] = Node(
            id=node_id,
            name=str(raw.get("name", node_id)),
            x=_parse_float(_section(raw, "x", where), where, "x"),
            y=_parse_float(_section(raw, "y", where), where, "y"),
            type=str(raw.get("type", "normal")),
        )

    roads: dict[Edge, Road] = {}
    for i, raw in enumerate(_section(data, "roads", path.name)):
        where = f"{path.name}: roads[{i}]"
        road = Road(
            from_node=str(_section(raw, "from", where)),
            to_node=str(_section(raw, "to", where)),
            distance=_parse_float(_section(raw, "distance", where), where, "distance"),
            speed=_parse_float(_section(raw, "speed", where), where, "speed"),
            road_type=str(raw.get("road_type", "")),
        )
        for endpoint in road.edge:
            if endpoint not in nodes:
                raise DataError(f"{where}: unknown node {endpoint!r}")
        if road.from_node == road.to_node:
            raise DataError(f"{where}: road from {road.from_node} to itself")
        if road.distance <= 0 or road.speed <= 0:
            raise DataError(f"{where}: distance and speed must be > 0")
        if road.edge in roads:
            raise DataError(f"{where}: duplicate road {road.from_node}->{road.to_node}")
        roads[road.edge] = road

    return Graph(nodes, roads)


def load_responders(path: Path, graph: Graph, warnings: list[str]) -> tuple[Responder, ...]:
    columns = ["responder_id", "type", "start_location", "capabilities",
               "availability", "time_until_available"]
    responders: dict[str, Responder] = {}
    for where, row in _read_csv(path, columns):
        rid = row["responder_id"]
        if rid in responders:
            raise DataError(f"{where}: duplicate responder id {rid!r}")
        _require_node(graph, row["start_location"], where)

        capabilities = frozenset(c.strip() for c in row["capabilities"].split(";") if c.strip())
        if not capabilities:
            raise DataError(f"{where}: responder {rid} has no capabilities")

        wait = _parse_float(row["time_until_available"] or 0, where, "time_until_available", 0.0)
        if row["availability"] == "Available":
            if wait > 0:
                warnings.append(f"{where}: {rid} is 'Available' but has time_until_available={wait}; using 0")
            available_from = 0.0
        elif row["availability"] == "Busy":
            available_from = wait
        else:
            raise DataError(f"{where}: availability {row['availability']!r} is not 'Available' or 'Busy'")

        responders[rid] = Responder(
            id=rid,
            type=_parse_enum(ResponderType, row["type"], where),
            start_location=row["start_location"],
            capabilities=capabilities,
            available_from=available_from,
        )
    if not responders:
        raise DataError(f"{path.name}: no responders")
    return tuple(responders.values())


def load_incidents(path: Path, graph: Graph, warnings: list[str]) -> tuple[Incident, ...]:
    columns = ["incident_id", "location", "priority", "deadline",
               "required_capability", "timestamp", "time_required"]
    incidents: dict[str, Incident] = {}
    for where, row in _read_csv(path, columns):
        iid = row["incident_id"]
        if iid in incidents:
            raise DataError(f"{where}: duplicate incident id {iid!r}")
        _require_node(graph, row["location"], where)
        if not row["required_capability"]:
            raise DataError(f"{where}: incident {iid} has no required capability")

        incident = Incident(
            id=iid,
            location=row["location"],
            priority=_parse_enum(Priority, row["priority"], where),
            deadline=_parse_float(row["deadline"], where, "deadline", 0.0),
            required_capability=row["required_capability"],
            timestamp=_parse_float(row["timestamp"], where, "timestamp", 0.0),
            time_required=_parse_float(row["time_required"], where, "time_required", 0.0),
        )
        if incident.deadline < incident.timestamp:
            warnings.append(f"{where}: {iid} has deadline {incident.deadline} before its "
                            f"timestamp {incident.timestamp}; it can never be met")
        incidents[iid] = incident
    return tuple(sorted(incidents.values(), key=lambda inc: (inc.timestamp, inc.id)))


def load_road_reports(path: Path, graph: Graph) -> dict[Edge, RoadEvidence]:
    columns = ["from", "to", "weather", "source", "reported_status"]
    weather: dict[Edge, Weather] = {}
    reports: dict[Edge, list[RoadReport]] = defaultdict(list)
    for where, row in _read_csv(path, columns):
        edge = (row["from"], row["to"])
        _require_road(graph, edge, where)
        road_weather = _parse_enum(Weather, row["weather"], where)
        # The README says weather is local to the reported road, so all reports
        # of one road must agree on it.
        if weather.setdefault(edge, road_weather) != road_weather:
            raise DataError(f"{where}: conflicting weather for road {edge[0]}->{edge[1]}")
        reports[edge].append(RoadReport(
            source=_parse_enum(ReportSource, row["source"], where),
            reported_status=_parse_enum(RoadStatus, row["reported_status"], where),
        ))
    return {edge: RoadEvidence(weather[edge], tuple(reps)) for edge, reps in reports.items()}


def load_road_cpts(path: Path) -> RoadCPTs:
    data = _read_json(path)
    name = path.name
    return RoadCPTs(
        weather_prior=_parse_distribution(
            _section(data, "weather_prior", name), Weather, f"{name}: weather_prior"),
        status_given_weather=_parse_conditional(
            _section(data, "road_status_given_weather", name), Weather, RoadStatus,
            f"{name}: road_status_given_weather"),
        report_given_status={
            source: _parse_conditional(_section(data, key, name), RoadStatus, RoadStatus, f"{name}: {key}")
            for source, key in _REPORT_CPT_KEYS.items()
        },
    )


def load_traffic_observations(path: Path, graph: Graph) -> dict[Edge, tuple[TrafficLevel, ...]]:
    columns = ["observation_nr", "from", "to", "traffic_observation"]
    sequences: dict[Edge, dict[int, TrafficLevel]] = defaultdict(dict)
    for where, row in _read_csv(path, columns):
        edge = (row["from"], row["to"])
        _require_road(graph, edge, where)
        number = _parse_float(row["observation_nr"], where, "observation_nr", 0.0)
        if not number.is_integer():
            raise DataError(f"{where}: observation_nr={number} is not an integer")
        if int(number) in sequences[edge]:
            raise DataError(f"{where}: duplicate observation_nr {int(number)} for {edge[0]}->{edge[1]}")
        sequences[edge][int(number)] = _parse_enum(TrafficLevel, row["traffic_observation"], where)
    # observation_nr only orders each road's own sequence; it is not a timestamp.
    return {edge: tuple(obs[n] for n in sorted(obs)) for edge, obs in sequences.items()}


def load_hmm(path: Path) -> HMMParams:
    data = _read_json(path)
    name = path.name
    return HMMParams(
        initial=_parse_distribution(_section(data, "initial", name), TrafficLevel, f"{name}: initial"),
        transition=_parse_conditional(_section(data, "transition", name), TrafficLevel, TrafficLevel,
                                      f"{name}: transition"),
        emission=_parse_conditional(_section(data, "emission", name), TrafficLevel, TrafficLevel,
                                    f"{name}: emission"),
    )


# --------------------------------------------------------------------------- #
# Whole scenario
# --------------------------------------------------------------------------- #

def load_scenario(folder: str | Path) -> Scenario:
    """Load and validate every input file of one scenario folder."""
    folder = Path(folder)
    if not folder.is_dir():
        raise DataError(f"scenario folder {folder} does not exist")

    def file(name: str) -> Path:
        path = folder / name
        if not path.is_file():
            raise DataError(f"{folder}: missing input file {name}")
        return path

    warnings: list[str] = []
    graph = load_graph(file("city_graph.json"))
    responders = load_responders(file("responders.csv"), graph, warnings)
    incidents = load_incidents(file("incidents.csv"), graph, warnings)

    all_capabilities = set().union(*(r.capabilities for r in responders))
    for incident in incidents:
        if incident.required_capability not in all_capabilities:
            warnings.append(f"{incident.id}: no responder has capability "
                            f"{incident.required_capability!r}; it cannot be handled")

    return Scenario(
        name=folder.name,
        graph=graph,
        responders=responders,
        incidents=incidents,
        road_evidence=load_road_reports(file("road_reports.csv"), graph),
        road_cpts=load_road_cpts(file("road_probabilities.json")),
        traffic_observations=load_traffic_observations(file("observed_traffic.csv"), graph),
        hmm=load_hmm(file("traffic_probabilities.json")),
        warnings=tuple(warnings),
    )
