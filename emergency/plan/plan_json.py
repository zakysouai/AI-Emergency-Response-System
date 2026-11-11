"""plan.json: the responder-incident assignments in the format of assignment 5.1 (design choice 14).

Only the four required keys are written; arrival times and lateness go to
statistics.txt. `time` is the departure time in seconds and is not rounded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from emergency.allocation import Assignment


def plan_entries(assignments: Iterable[Assignment]) -> list[dict]:
    return [{"responder_id": a.responder_id, "incident_id": a.incident_id,
             "path": list(a.path), "time": a.departure}
            for a in assignments]


def write_plan(path: Path, assignments: Iterable[Assignment]) -> None:
    path.write_text(json.dumps(plan_entries(assignments), indent=2) + "\n", encoding="utf-8")
