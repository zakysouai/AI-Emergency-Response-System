"""Uniform-cost search from one source to every node (design choice 5).

UCS without a goal test. The frontier is a priority queue ordered on g(n), the
cost so far. The first time a node leaves the queue its cost is final, because
every road cost is > 0; copies of that node still in the queue are stale and
skipped. Running until the queue is empty gives the cheapest route from the
source to every reachable node at once: Dijkstra's single-source shortest paths.

The allocation needs travel times between all relevant locations, so we run one
search per source instead of one per (source, goal) pair. A heuristic (A*)
needs a single goal and is therefore not used.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterable

from emergency.world import WorldModel


@dataclass(frozen=True)
class ShortestPaths:
    """Cheapest expected travel time and route from `source` to every reachable node.

    A node that is missing from `cost` cannot be reached from `source`.
    """

    source: str
    cost: dict[str, float]
    parent: dict[str, str | None]  # previous node on the cheapest route; None for the source

    def time_to(self, node: str) -> float | None:
        return self.cost.get(node)

    def path_to(self, node: str) -> list[str] | None:
        """[source, ..., node], or None if `node` cannot be reached."""
        if node not in self.parent:
            return None
        path = [node]
        while (prev := self.parent[path[-1]]) is not None:
            path.append(prev)
        return path[::-1]


def uniform_cost_search(world: WorldModel, source: str) -> ShortestPaths:
    if source not in world.graph.nodes:
        raise KeyError(f"unknown source node {source!r}")
    cost: dict[str, float] = {}
    parent: dict[str, str | None] = {}
    frontier: list[tuple[float, str, str | None]] = [(0.0, source, None)]  # (g, node, parent)
    while frontier:
        g, node, prev = heapq.heappop(frontier)
        if node in cost:
            continue  # stale copy: a cheaper route to this node was already found
        cost[node], parent[node] = g, prev
        for nxt, step in world.neighbors(node):
            if nxt not in cost:
                heapq.heappush(frontier, (g + step, nxt, node))
    return ShortestPaths(source, cost, parent)


def travel_table(world: WorldModel, sources: Iterable[str]) -> dict[str, ShortestPaths]:
    """One search per distinct source: table[a].time_to(b) is the travel time a -> b.

    Roads are directed, so table[a].time_to(b) and table[b].time_to(a) can differ.
    """
    return {source: uniform_cost_search(world, source) for source in sorted(set(sources))}
