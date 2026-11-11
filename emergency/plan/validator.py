"""Validation of a plan.json against a scenario (design choices 10 and 11).

The validator reads the plan as written to disk and replays every responder's
timeline on its own, from the paths and road costs; it does not reuse the
planner. It reports every problem it finds, each with a code:

  errors (plan is invalid)
    S1 not a JSON list            S2 not an object with exactly the 4 keys
    S3 wrong type (ids: non-empty strings, path: non-empty list of strings,
       time: finite number >= 0, not a bool)
    R1 unknown responder          R2 unknown incident
    R3 incident assigned twice    R4 responder lacks the capability
    P1 unknown node               P2 road does not exist
    P3 road is blocked (P(Blocked) > tau)
    P4 path does not end at the incident
    P5 path does not start where the responder is at that time
    T1 leaves before the incident is known
    T2 leaves before the responder is available
    T3 leaves before its previous task is finished
    T4 two tasks with the same start time, the first of which takes time
    C1 incident left out although a capable responder can reach it
  warnings (plan is valid but suspicious)
    W1 deadline missed            W2 incident left out, nobody can handle it
    W3 route slower than the fastest one
    W4 waits for no reason: leaves neither when it becomes free nor when
       new incidents appear

Times are compared with a tolerance of 1e-6 s.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

from emergency.data import Incident, Scenario
from emergency.search import uniform_cost_search
from emergency.world import WorldModel

KEYS = {"responder_id", "incident_id", "path", "time"}
EPS = 1e-6


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[Issue, ...]
    warnings: tuple[Issue, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {issue.code for issue in self.errors + self.warnings}


def validate_plan_text(text: str, scenario: Scenario, world: WorldModel) -> ValidationReport:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ValidationReport((Issue("S1", f"not valid JSON: {exc}"),), ())
    return validate_plan(data, scenario, world)


def _well_typed(entry: dict) -> bool:
    time, path = entry["time"], entry["path"]
    return (isinstance(entry["responder_id"], str) and entry["responder_id"] != ""
            and isinstance(entry["incident_id"], str) and entry["incident_id"] != ""
            and isinstance(path, list) and len(path) > 0 and all(isinstance(n, str) for n in path)
            and isinstance(time, (int, float)) and not isinstance(time, bool)
            and math.isfinite(time) and time >= 0)


def _route_time(path: list[str], incident: Incident, location: str, world: WorldModel,
                where: str, error: Callable, warn: Callable) -> float | None:
    """Checks P1-P5 and W3; returns the expected travel time, or None if it cannot be driven."""
    if path[0] != location:
        error("P5", f"{where}: path starts at {path[0]}, but the responder is at {location}")
    if path[-1] != incident.location:
        error("P4", f"{where}: path ends at {path[-1]}, but the incident is at {incident.location}")
    unknown = [n for n in path if n not in world.graph.nodes]
    if unknown:
        error("P1", f"{where}: unknown node(s) {unknown}")
        return None
    travel = 0.0
    for a, b in zip(path, path[1:]):
        if not world.graph.has_road(a, b):
            error("P2", f"{where}: there is no road {a}->{b}")
            return None
        if world.cost(a, b) is None:
            error("P3", f"{where}: road {a}->{b} is considered blocked")
            return None
        travel += world.cost(a, b)
    fastest = uniform_cost_search(world, path[0]).time_to(path[-1])
    if travel > fastest + EPS:
        warn("W3", f"{where}: route takes {travel:.1f} s, the fastest takes {fastest:.1f} s")
    return travel


def validate_plan(data: object, scenario: Scenario, world: WorldModel) -> ValidationReport:
    errors: list[Issue] = []
    warnings: list[Issue] = []

    def error(code: str, message: str) -> None:
        errors.append(Issue(code, message))

    def warn(code: str, message: str) -> None:
        warnings.append(Issue(code, message))

    if not isinstance(data, list):
        error("S1", "plan.json must contain a JSON list")
        return ValidationReport(tuple(errors), ())

    responders = {r.id: r for r in scenario.responders}
    incidents = {i.id: i for i in scenario.incidents}
    entries = []  # (index, entry) that passed the structure and reference checks
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or set(entry) != KEYS:
            error("S2", f"entry {index}: must be an object with exactly the keys {sorted(KEYS)}")
        elif not _well_typed(entry):
            error("S3", f"entry {index}: wrong type or value in {entry}")
        else:
            if entry["responder_id"] not in responders:
                error("R1", f"entry {index}: unknown responder {entry['responder_id']!r}")
            if entry["incident_id"] not in incidents:
                error("R2", f"entry {index}: unknown incident {entry['incident_id']!r}")
            if entry["responder_id"] in responders and entry["incident_id"] in incidents:
                entries.append((index, entry))
    for iid, count in Counter(e["incident_id"] for _, e in entries).items():
        if count > 1:
            error("R3", f"incident {iid} is assigned {count} times")

    # Replay each responder's tasks in order of start time.
    event_times = sorted({i.timestamp for i in scenario.incidents})
    by_responder = defaultdict(list)
    for index, entry in entries:
        by_responder[entry["responder_id"]].append((entry["time"], index, entry))
    for rid, tasks in by_responder.items():
        r = responders[rid]
        free, location, previous_start = r.available_from, r.start_location, None
        for time, index, entry in sorted(tasks, key=lambda t: t[:2]):
            inc = incidents[entry["incident_id"]]
            where = f"entry {index} ({rid} -> {inc.id})"
            if not r.can_handle(inc.required_capability):
                error("R4", f"{where}: {rid} cannot do {inc.required_capability!r}")
            travel = _route_time(entry["path"], inc, location, world, where, error, warn)
            if time < inc.timestamp - EPS:
                error("T1", f"{where}: leaves at {time:g}, but the incident is only known at {inc.timestamp:g}")
            if time < r.available_from - EPS:
                error("T2", f"{where}: leaves at {time:g}, but {rid} is only available at {r.available_from:g}")
            if previous_start is not None and free is not None and time < free - EPS:
                if abs(time - previous_start) <= EPS:
                    error("T4", f"{where}: starts at the same time as {rid}'s previous task")
                else:
                    error("T3", f"{where}: leaves at {time:g}, but {rid} is busy until {free:g}")
            if free is not None and time > free + EPS and not any(
                    abs(time - t) <= EPS for t in event_times if t >= inc.timestamp - EPS):
                warn("W4", f"{where}: free at {free:g} but only leaves at {time:g}")
            if travel is None:
                free = None  # arrival unknown: later timing checks of this responder are skipped
            else:
                arrival = time + travel
                if arrival > inc.deadline + EPS:
                    warn("W1", f"{where}: arrives at {arrival:.1f}, deadline {inc.deadline:g}")
                free = arrival + inc.time_required
            location, previous_start = inc.location, time

    # Every incident must be handled, unless nobody is able to.
    planned = {e["incident_id"] for _, e in entries}
    for inc in scenario.incidents:
        if inc.id in planned:
            continue
        able = [r.id for r in scenario.responders if r.can_handle(inc.required_capability)
                and uniform_cost_search(world, r.start_location).time_to(inc.location) is not None]
        if able:
            error("C1", f"incident {inc.id} is not handled, although {able} could reach it")
        else:
            warn("W2", f"incident {inc.id} is not handled: no capable responder can reach it")
    return ValidationReport(tuple(errors), tuple(warnings))
