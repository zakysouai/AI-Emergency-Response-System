"""Event loop: plan again every time new incidents become known (design choices 7 and 9).

Incidents only exist from their timestamp on, so at each timestamp `now` the
CSP is solved for the incidents that just appeared. With `revise=False` every
earlier assignment stays as it is and new incidents can only come after a
responder's existing tasks. With `revise=True` the tasks that have not departed
yet (departure > now) are taken back and planned again together with the new
incidents. Travel times are the world model's expected times; nothing is random.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from emergency.data import Incident, Scenario
from emergency.search import travel_table
from emergency.world import WorldModel

from .csp import Assignment, ResponderState, schedule_chain, solve_event


@dataclass(frozen=True)
class SimulationResult:
    assignments: tuple[Assignment, ...]  # sorted on departure, then responder
    unhandled: tuple[Incident, ...]  # no capable responder could reach them
    warnings: tuple[str, ...]


def simulate(scenario: Scenario, world: WorldModel, revise: bool = False,
             node_limit: int = 100_000) -> SimulationResult:
    responders = scenario.responders
    incidents = {inc.id: inc for inc in scenario.incidents}
    table = travel_table(world, [r.start_location for r in responders] +
                         [inc.location for inc in scenario.incidents])
    plans: dict[str, list[Assignment]] = {r.id: [] for r in responders}
    unhandled: list[Incident] = []
    warnings: list[str] = []

    for now, group in groupby(scenario.incidents, key=lambda inc: inc.timestamp):
        to_plan = list(group)
        states = {}
        for r in responders:
            if revise:
                taken_back = [a for a in plans[r.id] if a.departure > now]
                to_plan += [incidents[a.incident_id] for a in taken_back]
                plans[r.id] = [a for a in plans[r.id] if a.departure <= now]
            last = plans[r.id][-1] if plans[r.id] else None
            states[r.id] = (ResponderState(last.finish, last.path[-1]) if last
                            else ResponderState(r.available_from, r.start_location))

        solution = solve_event(now, to_plan, responders, states, table, node_limit)
        for rid, chain in solution.chains.items():
            plans[rid] += schedule_chain(rid, states[rid], chain, now, table)
        unhandled += solution.unhandled
        if not solution.complete:
            warnings.append(f"t={now:g}: node limit {node_limit} reached; "
                            f"using the best plan found so far")

    assignments = sorted((a for plan in plans.values() for a in plan),
                         key=lambda a: (a.departure, a.responder_id))
    return SimulationResult(tuple(assignments), tuple(unhandled), tuple(warnings))
