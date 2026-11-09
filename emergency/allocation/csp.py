"""One planning event as a constraint optimization problem (design choices 6-8).

Variables are the incidents to plan; a value is (responder, position in that
responder's chain of tasks). Hard constraints: the responder has the required
capability, every leg of its chain is reachable, and it handles one incident
at a time. Every solution is scored with the tuple

    (#Critical on time, #High, #Medium, #Low, #handled, -total response time)

compared lexicographically, so deadlines of more urgent incidents always win,
and late incidents still get the best remaining place.

Branch-and-bound is valid because inserting an incident into a chain never
makes the tasks after it earlier (UCS distances obey the triangle inequality),
so the score of a partial solution can only drop as more incidents are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from emergency.data import Incident, Priority, Responder
from emergency.search import ShortestPaths

Score = tuple[float, ...]  # one count per priority, #handled, -total response time
_SIZE = len(Priority) + 2
_ZERO: Score = (0.0,) * _SIZE


@dataclass(frozen=True)
class ResponderState:
    free_at: float  # when the responder has finished every task that stays fixed
    location: str  # where it is at that time


@dataclass(frozen=True)
class Assignment:
    responder_id: str
    incident_id: str
    path: tuple[str, ...]
    departure: float
    arrival: float
    finish: float  # arrival + time required on site


@dataclass(frozen=True)
class EventSolution:
    chains: dict[str, list[Incident]]  # responder id -> incidents in the order they are handled
    unhandled: list[Incident]
    nodes: int
    complete: bool  # False if the node limit stopped the search early


def _legs(state: ResponderState, chain: Sequence[Incident], now: float,
          table: Mapping[str, ShortestPaths]) -> list[tuple[Incident, str, float, float]] | None:
    """(incident, from, departure, arrival) per task; None if a leg is unreachable.

    A responder leaves as soon as it is free, but never before `now`.
    """
    free, location = max(state.free_at, now), state.location
    legs = []
    for incident in chain:
        travel = table[location].time_to(incident.location)
        if travel is None:
            return None
        legs.append((incident, location, free, free + travel))
        free, location = free + travel + incident.time_required, incident.location
    return legs


def schedule_chain(responder_id: str, state: ResponderState, chain: Sequence[Incident],
                   now: float, table: Mapping[str, ShortestPaths]) -> list[Assignment] | None:
    """The chain as assignments with routes; None if a leg is unreachable."""
    legs = _legs(state, chain, now, table)
    if legs is None:
        return None
    return [Assignment(responder_id, inc.id, tuple(table[src].path_to(inc.location)),
                       departure, arrival, arrival + inc.time_required)
            for inc, src, departure, arrival in legs]


def _chain_score(state: ResponderState, chain: Sequence[Incident], now: float,
                 table: Mapping[str, ShortestPaths]) -> tuple[Score, list[float]] | None:
    """Score contribution and arrival times of one chain (no routes: this runs at every node)."""
    legs = _legs(state, chain, now, table)
    if legs is None:
        return None
    score = list(_ZERO)
    for incident, _, _, arrival in legs:
        if arrival <= incident.deadline:
            score[incident.priority.rank] += 1
        score[-2] += 1
        score[-1] -= arrival - incident.timestamp
    return tuple(score), [arrival for *_, arrival in legs]


def _add(a: Score, b: Score) -> Score:
    return tuple(x + y for x, y in zip(a, b))


def solve_event(now: float, incidents: Sequence[Incident], responders: Sequence[Responder],
                states: Mapping[str, ResponderState], table: Mapping[str, ShortestPaths],
                node_limit: int = 100_000) -> EventSolution:
    """Best chains for `incidents`, starting from the given responder states."""
    candidates = {inc.id: [r.id for r in responders if r.can_handle(inc.required_capability)]
                  for inc in incidents}
    # Most urgent first, then the tightest deadline, then the fewest options (MRV-like).
    order = sorted(incidents, key=lambda i: (i.priority.rank, i.deadline, len(candidates[i.id]), i.id))
    # remaining[k]: optimistic score of order[k:], as if all were handled on time with no delay.
    remaining = [_ZERO] * (len(order) + 1)
    for k in range(len(order) - 1, -1, -1):
        bonus = [0.0] * _SIZE
        bonus[order[k].priority.rank] = bonus[-2] = 1
        remaining[k] = _add(remaining[k + 1], tuple(bonus))

    chains: dict[str, list[Incident]] = {r.id: [] for r in responders}
    contrib: dict[str, Score] = {r.id: _ZERO for r in responders}
    unhandled: list[Incident] = []
    best: tuple[Score, dict[str, list[Incident]], list[Incident]] | None = None
    nodes, stopped = 0, False

    def total() -> Score:
        score = _ZERO
        for part in contrib.values():
            score = _add(score, part)
        return score

    def search(k: int) -> None:
        nonlocal best, nodes, stopped
        if best is not None and nodes >= node_limit:
            stopped = True  # keep the best solution found so far
            return
        nodes += 1
        score = total()
        if best is not None and _add(score, remaining[k]) <= best[0]:
            return  # even the best case cannot beat the best solution found so far
        if k == len(order):
            best = (score, {rid: list(c) for rid, c in chains.items() if c}, list(unhandled))
            return
        incident = order[k]
        options = []
        for rid in candidates[incident.id]:
            for pos in range(len(chains[rid]) + 1):
                new_chain = chains[rid][:pos] + [incident] + chains[rid][pos:]
                evaluated = _chain_score(states[rid], new_chain, now, table)
                if evaluated is not None:
                    part, arrivals = evaluated
                    options.append((arrivals[pos], rid, pos, new_chain, part))
        options.sort(key=lambda o: o[:3])  # earliest arrival first: good bounds early
        for _, rid, _, new_chain, part in options:
            old = chains[rid], contrib[rid]
            chains[rid], contrib[rid] = new_chain, part
            search(k + 1)
            chains[rid], contrib[rid] = old
        unhandled.append(incident)  # last resort: ranks below every handled option
        search(k + 1)
        unhandled.pop()

    search(0)
    _, best_chains, best_unhandled = best
    return EventSolution(best_chains, best_unhandled, nodes, complete=not stopped)
