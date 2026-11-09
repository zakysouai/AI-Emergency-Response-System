"""Bayesian estimate of each road's true status.

Bayesian network per directed road:

    Weather ──> Status ──> Citizen report
                       ├─> Police report
                       └─> Sensor report

Assumption: reports are conditionally independent given the true status, so

    P(Status | weather, reports) = α · P(Status | weather) · Π_i P(report_i | Status)

Exact inference by enumeration; the network is small enough for that.
"""

from __future__ import annotations

from ..data.models import RoadCPTs, RoadEvidence, RoadStatus, Weather
from .distributions import normalize


def status_prior(cpts: RoadCPTs, weather: Weather | None) -> dict[RoadStatus, float]:
    """P(Status | weather), or P(Status) = Σ_w P(w)·P(Status | w) when the weather is unknown."""
    if weather is not None:
        return dict(cpts.status_given_weather[weather])
    # Design choice 1: roads without reports have unknown weather -> sum it out.
    return {
        status: sum(cpts.weather_prior[w] * cpts.status_given_weather[w][status] for w in Weather)
        for status in RoadStatus
    }


def road_posterior(cpts: RoadCPTs, evidence: RoadEvidence | None) -> dict[RoadStatus, float]:
    """P(Status | weather, reports) for one road; `evidence` is None for unreported roads."""
    if evidence is None:
        return status_prior(cpts, None)
    belief = status_prior(cpts, evidence.weather)
    for report in evidence.reports:
        likelihood = cpts.report_given_status[report.source]
        belief = {status: p * likelihood[status][report.reported_status] for status, p in belief.items()}
    return normalize(belief)
