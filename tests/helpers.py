"""Shared test helpers: small hand-made worlds whose numbers can be checked on paper."""

from emergency.data import Graph, Node, Road, RoadStatus, TrafficLevel
from emergency.world import RoadBelief, WorldModel, WorldParams


def toy_world(costs, extra_nodes=()):
    """A world in which each road costs exactly the given number (None = unusable)."""
    names = {n for edge in costs for n in edge} | set(extra_nodes)
    nodes = {n: Node(n, n, 0.0, 0.0, "normal") for n in names}
    roads = {(a, b): Road(a, b, 1.0, 1.0, "main") for a, b in costs}
    certain = ({s: float(s is RoadStatus.OPEN) for s in RoadStatus},
               {t: float(t is TrafficLevel.LOW) for t in TrafficLevel})
    beliefs = {edge: RoadBelief(*certain, cost) for edge, cost in costs.items()}
    return WorldModel(Graph(nodes, roads), beliefs, WorldParams())
