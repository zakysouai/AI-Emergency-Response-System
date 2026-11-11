"""statistics.txt: how well the plan does (assignment 5.2, design choice 12).

All times are simulation seconds and are the world model's EXPECTED times, so
these numbers say how good the plan is under our own model, not in reality.

  handled          incidents in the plan, also the ones that arrive late
  responders used  responders with at least one task
  response time    arrival - timestamp, averaged over the handled incidents
  deadlines met    arrival <= deadline, divided by ALL incidents: an
                   unhandled incident counts as a missed deadline
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from emergency.allocation import Assignment
from emergency.data import Priority, Scenario

from .validator import ValidationReport


@dataclass(frozen=True)
class Statistics:
    incidents: int
    handled: int
    responders: int
    responders_used: int
    average_response: float | None  # None when nothing is handled
    met: int
    met_by_priority: dict[Priority, tuple[int, int]]  # priority -> (met, total)
    late: tuple[tuple[str, float, float], ...]  # (incident, arrival, deadline)
    unhandled: tuple[str, ...]

    @property
    def met_percentage(self) -> float | None:
        return 100 * self.met / self.incidents if self.incidents else None


def compute_statistics(scenario: Scenario, assignments: Iterable[Assignment]) -> Statistics:
    arrival = {a.incident_id: a.arrival for a in assignments}
    used = {a.responder_id for a in assignments}
    on_time = {i.id for i in scenario.incidents if i.id in arrival and arrival[i.id] <= i.deadline}
    met_by_priority = {}
    for p in Priority:
        group = [i for i in scenario.incidents if i.priority is p]
        if group:
            met_by_priority[p] = (sum(i.id in on_time for i in group), len(group))
    handled = [i for i in scenario.incidents if i.id in arrival]
    responses = [arrival[i.id] - i.timestamp for i in handled]
    return Statistics(
        incidents=len(scenario.incidents),
        handled=len(handled),
        responders=len(scenario.responders),
        responders_used=len(used),
        average_response=sum(responses) / len(responses) if responses else None,
        met=len(on_time),
        met_by_priority=met_by_priority,
        late=tuple((i.id, arrival[i.id], i.deadline) for i in handled if i.id not in on_time),
        unhandled=tuple(i.id for i in scenario.incidents if i.id not in arrival),
    )


def format_statistics(stats: Statistics, scenario_name: str, settings: dict[str, object],
                      report: ValidationReport) -> str:
    average = "n/a" if stats.average_response is None else f"{stats.average_response:.1f} s"
    percentage = "n/a" if stats.met_percentage is None else f"{stats.met_percentage:.1f}%"
    lines = [
        "System statistics :",
        f" * {stats.handled} incidents handled",
        f" * {stats.responders_used} responders used",
        f" * Average response time : {average}",
        f" * Deadlines met : {percentage}",
        "",
        f"Scenario: {scenario_name} ({stats.incidents} incidents, {stats.responders} responders)",
        "Settings: " + ", ".join(f"{k} = {v}" for k, v in settings.items()),
        "",
        "Deadlines met per priority:",
        *(f" * {p.value}: {met}/{total}" for p, (met, total) in stats.met_by_priority.items()),
        "Late incidents (expected arrival > deadline):",
        *(f" * {iid}: arrives at {arr:.1f} s, deadline {dl:g} s" for iid, arr, dl in stats.late),
        *([] if stats.late else [" * none"]),
        "Unhandled incidents:",
        *(f" * {iid}" for iid in stats.unhandled),
        *([] if stats.unhandled else [" * none"]),
        "",
        f"Validation of plan.json: {'valid' if report.valid else 'INVALID'} "
        f"({len(report.errors)} errors, {len(report.warnings)} warnings)",
        *(f" * error {i.code}: {i.message}" for i in report.errors),
        *(f" * warning {i.code}: {i.message}" for i in report.warnings if i.code != "W1"),
        "",
        "Definitions (time unit: seconds of simulation time):",
        " * The numbers above use the world model's expected travel times.",
        " * Handled: incidents that have a responder in plan.json, also when late.",
        " * Responders used: responders with at least one task in plan.json.",
        " * Response time: expected arrival - time the incident became known;",
        "   averaged over the handled incidents only.",
        " * Deadlines met: incidents reached at or before their deadline, divided",
        "   by all incidents; an unhandled incident counts as a missed deadline.",
    ]
    return "\n".join(lines) + "\n"
