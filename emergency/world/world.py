"""The world model: one expected travel time (or "unusable") per directed road.

All road reports and traffic observations are known at time 0, so the world
is built once and stays fixed during the simulation.

Cost of a road with base time t (design choices 2 and 3):

    unusable                                         if P(Blocked) > τ
    t · (P_O + c·P_C) / (P_O + P_C) · Σ_l P(l)·m_l   otherwise

with c the congestion factor and m_l the factor of traffic level l. The status
part is the expected factor *given that the road is not blocked*; status and
traffic are multiplied because they are treated as independent causes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..data.models import Edge, Graph, RoadStatus, Scenario, TrafficLevel
from .bayes import road_posterior
from .distributions import expected_value
from .hmm import filter_traffic


def _default_traffic_factors() -> dict[TrafficLevel, float]:
    return {TrafficLevel.LOW: 1.0, TrafficLevel.MEDIUM: 1.2, TrafficLevel.HIGH: 1.5}


@dataclass(frozen=True)
class WorldParams:
    blocked_threshold: float = 0.5  # τ: a road is unusable when P(Blocked) > τ
    congested_factor: float = 1.5  # given by the assignment
    traffic_factors: Mapping[TrafficLevel, float] = field(default_factory=_default_traffic_factors)

    def __post_init__(self):
        if set(self.traffic_factors) != set(TrafficLevel):
            raise ValueError("traffic_factors needs a factor for every traffic level")
        # Every cost must be >= the road's base time, otherwise the A* heuristic
        # (straight-line distance / max speed) is no longer admissible.
        if min(self.congested_factor, *self.traffic_factors.values()) < 1:
            raise ValueError("all slowdown factors must be >= 1")


@dataclass(frozen=True)
class RoadBelief:
    status: dict[RoadStatus, float]  # P(Status | weather, reports)
    traffic: dict[TrafficLevel, float]  # P(traffic now | observations)
    expected_time: float | None  # seconds; None when the road is unusable

    @property
    def p_blocked(self) -> float:
        return self.status[RoadStatus.BLOCKED]

    @property
    def usable(self) -> bool:
        return self.expected_time is not None


def expected_travel_time(base_time: float, status: Mapping[RoadStatus, float],
                         traffic: Mapping[TrafficLevel, float], params: WorldParams) -> float | None:
    """The cost formula from the module docstring, for a single road."""
    p_open, p_congested = status[RoadStatus.OPEN], status[RoadStatus.CONGESTED]
    # p_open + p_congested > 0 also guards the division when τ = 1 and P(Blocked) = 1.
    if status[RoadStatus.BLOCKED] > params.blocked_threshold or p_open + p_congested <= 0:
        return None
    status_factor = (p_open + params.congested_factor * p_congested) / (p_open + p_congested)
    traffic_factor = expected_value(traffic, params.traffic_factors)
    return base_time * status_factor * traffic_factor


class WorldModel:
    def __init__(self, graph: Graph, beliefs: dict[Edge, RoadBelief], params: WorldParams):
        self.graph = graph
        self.beliefs = beliefs
        self.params = params

    def cost(self, from_node: str, to_node: str) -> float | None:
        """Expected travel time of a road; None if it is unusable or does not exist."""
        belief = self.beliefs.get((from_node, to_node))
        return belief.expected_time if belief else None

    def neighbors(self, node_id: str) -> list[tuple[str, float]]:
        """(next node, cost) for every usable road leaving `node_id`; the successors for search."""
        result = []
        for road in self.graph.outgoing(node_id):
            belief = self.beliefs[road.edge]
            if belief.usable:
                result.append((road.to_node, belief.expected_time))
        return result

    def route_reliability(self, path: Sequence[str]) -> float:
        """P(no road on the path is blocked) = Π (1 − P(Blocked)), treating roads as independent."""
        return math.prod(1 - self.beliefs[edge].p_blocked for edge in zip(path, path[1:]))


def build_world(scenario: Scenario, params: WorldParams | None = None) -> WorldModel:
    params = params or WorldParams()
    beliefs = {}
    for edge, road in scenario.graph.roads.items():
        status = road_posterior(scenario.road_cpts, scenario.road_evidence.get(edge))
        traffic = filter_traffic(scenario.hmm, scenario.traffic_observations.get(edge, ()))
        beliefs[edge] = RoadBelief(status, traffic, expected_travel_time(road.base_time, status, traffic, params))
    return WorldModel(scenario.graph, beliefs, params)
