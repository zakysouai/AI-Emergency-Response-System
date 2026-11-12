"""Monte Carlo evaluation of a fixed plan (design choices 15-18).

The plan is made with expected travel times. Here it is executed in N sampled
"true" worlds to see how often the deadlines are really met:

  sampling   every directed road independently gets a status from
             P(Status | weather, reports) and a traffic level from the filtered
             HMM distribution of the `truth` world model (choice 15)
  travel     Open: t * m_traffic, Congested: t * 1.5 * m_traffic, Blocked:
             unusable, with the same factors as the world model (choice 17)
  execution  a responder leaves at max(planned departure, actually free) and
             follows its planned path. At the start of a blocked road it learns
             that the road is blocked and searches a new route with UCS in the
             expected world without the blocked roads it knows. Without any
             route the incident fails and the responder stays where it is (16)

Every plan is executed in the same sampled worlds (common random numbers), so
two plans can be compared without the noise of different samples.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from emergency.allocation import Assignment
from emergency.data import Edge, RoadStatus, Scenario
from emergency.search import uniform_cost_search
from emergency.world import WorldModel


@dataclass(frozen=True)
class SampledWorld:
    blocked: frozenset[Edge]
    time: dict[Edge, float]  # true travel time of every road that is not blocked


def sample_worlds(truth: WorldModel, n: int, seed: int) -> list[SampledWorld]:
    rng = random.Random(seed)
    params = truth.params
    worlds = []
    for _ in range(n):
        blocked, time = set(), {}
        for edge, road in truth.graph.roads.items():
            belief = truth.beliefs[edge]
            status = rng.choices(list(belief.status), weights=list(belief.status.values()))[0]
            traffic = rng.choices(list(belief.traffic), weights=list(belief.traffic.values()))[0]
            if status is RoadStatus.BLOCKED:
                blocked.add(edge)
            else:
                congested = params.congested_factor if status is RoadStatus.CONGESTED else 1.0
                time[edge] = road.base_time * congested * params.traffic_factors[traffic]
        worlds.append(SampledWorld(frozenset(blocked), time))
    return worlds


class _KnownWorld:
    """The expected world without the roads a responder has found blocked (for UCS)."""

    def __init__(self, world: WorldModel, blocked: set[Edge]):
        self.graph, self._world, self._blocked = world.graph, world, blocked

    def neighbors(self, node: str) -> list[tuple[str, float]]:
        return [(nxt, c) for nxt, c in self._world.neighbors(node) if (node, nxt) not in self._blocked]


def _drive(route: list[str] | None, node: str, goal: str, t: float, world: WorldModel,
           sample: SampledWorld, known: set[Edge]) -> tuple[str, float, bool]:
    """Drives towards `goal`; returns (where it ends, when, whether it got there)."""
    if not route or route[0] != node:
        route = uniform_cost_search(_KnownWorld(world, known), node).path_to(goal)
    while route is not None:
        if node == goal:
            return node, t, True
        edge = (node, route[1])
        if edge in sample.blocked:
            known.add(edge)
            route = uniform_cost_search(_KnownWorld(world, known), node).path_to(goal)
            continue
        t += sample.time[edge]
        node, route = route[1], route[1:]
    return node, t, False


def execute(scenario: Scenario, plan: Sequence[Assignment], world: WorldModel,
            sample: SampledWorld) -> dict[str, float]:
    """Real arrival time per incident that is reached; incidents that fail are missing."""
    incidents = {i.id: i for i in scenario.incidents}
    tasks = defaultdict(list)
    for a in plan:
        tasks[a.responder_id].append(a)
    arrival = {}
    for r in scenario.responders:
        node, free, known = r.start_location, r.available_from, set()
        for a in sorted(tasks[r.id], key=lambda a: a.departure):
            inc = incidents[a.incident_id]
            node, t, reached = _drive(list(a.path), node, inc.location, max(a.departure, free),
                                      world, sample, known)
            if reached:
                arrival[inc.id] = t
                free = t + inc.time_required
            else:
                free = t
    return arrival


@dataclass(frozen=True)
class MonteCarloResult:
    met: tuple[float, ...]  # % of ALL incidents on time, per sample (empty without incidents)
    response: tuple[float, ...]  # average response time of the reached incidents, per sample
    not_reached: tuple[int, ...]  # incidents in the plan that were not reached, per sample
    p_on_time: dict[str, float]  # incident -> fraction of samples on time

    @staticmethod
    def mean_ci(values: Sequence[float]) -> tuple[float, float]:
        """Mean and half-width of its 95% confidence interval (normal approximation)."""
        if len(values) < 2:
            return (values[0] if values else float("nan")), float("nan")
        return statistics.fmean(values), 1.96 * statistics.stdev(values) / len(values) ** 0.5


def evaluate(scenario: Scenario, plan: Sequence[Assignment], world: WorldModel,
             worlds: Sequence[SampledWorld]) -> MonteCarloResult:
    met, response, not_reached = [], [], []
    on_time = dict.fromkeys((i.id for i in scenario.incidents), 0)
    for sample in worlds:
        arrival = execute(scenario, plan, world, sample)
        late_or_missing = 0
        for inc in scenario.incidents:
            if inc.id in arrival and arrival[inc.id] <= inc.deadline:
                on_time[inc.id] += 1
            else:
                late_or_missing += 1
        if scenario.incidents:  # without incidents there is no percentage (as in statistics.py)
            met.append(100 * (1 - late_or_missing / len(scenario.incidents)))
        times = [arrival[i.id] - i.timestamp for i in scenario.incidents if i.id in arrival]
        if times:
            response.append(statistics.fmean(times))
        not_reached.append(len(plan) - len(arrival))
    n = len(worlds)
    return MonteCarloResult(tuple(met), tuple(response), tuple(not_reached),
                            {iid: count / n for iid, count in on_time.items()})


def _mean_text(values: Sequence[float], unit: str) -> str:
    if not values:
        return "n/a"
    mean, ci = MonteCarloResult.mean_ci(values)
    return f"{mean:.1f}{unit} +- {ci:.1f}"


def format_monte_carlo(result: MonteCarloResult, seed: int) -> str:
    lines = [
        f"Monte Carlo ({len(result.not_reached)} sampled worlds, seed {seed}): the plan above executed",
        "in sampled true road states; responders detour around blocked roads.",
        f" * Deadlines met: {_mean_text(result.met, '%')}",
        f" * Average response time: {_mean_text(result.response, ' s')} (reached incidents)",
        f" * Incidents not reached: {statistics.fmean(result.not_reached):.2f} per world",
        " * P(on time) per incident: " + ", ".join(f"{iid} {p:.2f}" for iid, p in result.p_on_time.items()),
        " (+- is the half-width of the 95% confidence interval of the mean.)",
    ]
    return "\n".join(lines) + "\n"
