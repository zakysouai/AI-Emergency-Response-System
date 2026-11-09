"""Allocation: which responder handles which incident, in what order (CSP + event loop)."""

from .csp import Assignment, EventSolution, ResponderState, schedule_chain, solve_event
from .simulation import SimulationResult, simulate
