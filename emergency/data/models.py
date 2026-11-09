"""Typed, immutable representation of one scenario's input data.

Units used everywhere in the project:
    distance  -> metres
    speed     -> metres per second
    time      -> seconds (simulation time, fractional values allowed)

These objects describe the *initial* state only. Anything that changes during
the simulation (a responder's current location, when it becomes free again)
belongs to the simulation layer, not here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# A directed road is identified by its (from, to) node ids.
Edge = tuple[str, str]


class RoadStatus(Enum):
    OPEN = "Open"
    CONGESTED = "Congested"
    BLOCKED = "Blocked"


class Weather(Enum):
    CLEAR = "Clear"
    RAIN = "Rain"
    STORM = "Storm"


class ReportSource(Enum):
    CITIZEN = "Citizen"
    POLICE = "Police"
    SENSOR = "Sensor"


class TrafficLevel(Enum):
    """Used both as hidden HMM state and as observation symbol."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ResponderType(Enum):
    AMBULANCE = "Ambulance"
    POLICE_UNIT = "PoliceUnit"
    FIRE_TRUCK = "FireTruck"


class Priority(Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

    @property
    def rank(self) -> int:
        """0 is the most urgent; useful for sorting incidents."""
        return _PRIORITY_RANK[self]


_PRIORITY_RANK = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    x: float
    y: float
    type: str  # e.g. "normal", "hospital", "fire_station", "police"


@dataclass(frozen=True)
class Road:
    """One *directed* road. The reverse direction is a separate Road."""

    from_node: str
    to_node: str
    distance: float
    speed: float
    road_type: str  # "main" or "secondary"

    @property
    def edge(self) -> Edge:
        return (self.from_node, self.to_node)

    @property
    def base_time(self) -> float:
        """Travel time in seconds under normal (Open, no traffic) conditions."""
        return self.distance / self.speed


class Graph:
    """The city road network as a directed graph with an adjacency list."""

    def __init__(self, nodes: dict[str, Node], roads: dict[Edge, Road]):
        self.nodes = nodes
        self.roads = roads
        self._outgoing: dict[str, list[Road]] = {node_id: [] for node_id in nodes}
        for road in roads.values():
            self._outgoing[road.from_node].append(road)

    def outgoing(self, node_id: str) -> list[Road]:
        """Roads leaving `node_id` (the successors used by search)."""
        return self._outgoing[node_id]

    def road(self, from_node: str, to_node: str) -> Road | None:
        return self.roads.get((from_node, to_node))

    def has_road(self, from_node: str, to_node: str) -> bool:
        return (from_node, to_node) in self.roads

    def euclidean(self, a: str, b: str) -> float:
        """Straight-line distance in metres between two nodes."""
        na, nb = self.nodes[a], self.nodes[b]
        return math.hypot(na.x - nb.x, na.y - nb.y)


@dataclass(frozen=True)
class Responder:
    id: str
    type: ResponderType
    start_location: str
    capabilities: frozenset[str]
    # Earliest simulation time at which the responder can start a task:
    # 0 when "Available", otherwise its `time_until_available`.
    available_from: float

    def can_handle(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class Incident:
    id: str
    location: str
    priority: Priority
    deadline: float  # absolute time by which a responder must have ARRIVED
    required_capability: str
    timestamp: float  # time at which the incident becomes known
    time_required: float  # how long the responder is busy after arrival


@dataclass(frozen=True)
class RoadReport:
    source: ReportSource
    reported_status: RoadStatus


@dataclass(frozen=True)
class RoadEvidence:
    """All reports about one directed road, plus the weather local to that road."""

    weather: Weather
    reports: tuple[RoadReport, ...]


@dataclass(frozen=True)
class RoadCPTs:
    """Conditional probability tables from road_probabilities.json."""

    weather_prior: dict[Weather, float]  # P(Weather)
    status_given_weather: dict[Weather, dict[RoadStatus, float]]  # P(Status | Weather)
    # P(Reported | Status) per source: report_given_status[source][true][reported]
    report_given_status: dict[ReportSource, dict[RoadStatus, dict[RoadStatus, float]]]


@dataclass(frozen=True)
class HMMParams:
    """Traffic HMM from traffic_probabilities.json."""

    initial: dict[TrafficLevel, float]  # P(X_1)
    transition: dict[TrafficLevel, dict[TrafficLevel, float]]  # P(X_t+1 | X_t)
    emission: dict[TrafficLevel, dict[TrafficLevel, float]]  # P(E_t | X_t)


@dataclass(frozen=True)
class Scenario:
    name: str
    graph: Graph
    responders: tuple[Responder, ...]
    incidents: tuple[Incident, ...]  # sorted by timestamp, then id
    road_evidence: dict[Edge, RoadEvidence]  # only roads that have reports
    road_cpts: RoadCPTs
    traffic_observations: dict[Edge, tuple[TrafficLevel, ...]]  # ordered by observation_nr
    hmm: HMMParams
    # Non-fatal oddities found while loading (e.g. an impossible deadline).
    warnings: tuple[str, ...] = ()
