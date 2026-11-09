"""Traffic level per road via HMM filtering (the forward algorithm).

Hidden state X_t = true traffic level, evidence E_t = observed level.

    f_1     = α · P(E_1 | X_1) · P(X_1)
    f_{t+1} = α · P(E_{t+1} | X_{t+1}) · Σ_x P(X_{t+1} | x) · f_t(x)

f_t is P(X_t | e_1..e_t): the belief about traffic *after* the last observation.

Assumption: `initial` in the data is P(X_1), the state at the first
observation, so there is no transition step before it.
"""

from __future__ import annotations

from typing import Sequence

from ..data.models import HMMParams, TrafficLevel
from .distributions import normalize


def filter_traffic(hmm: HMMParams, observations: Sequence[TrafficLevel]) -> dict[TrafficLevel, float]:
    """P(X_T | e_1..e_T); returns `initial` when the road has no observations."""
    if not observations:
        return dict(hmm.initial)
    belief = normalize({x: hmm.initial[x] * hmm.emission[x][observations[0]] for x in TrafficLevel})
    for obs in observations[1:]:
        predicted = {x: sum(belief[prev] * hmm.transition[prev][x] for prev in TrafficLevel)
                     for x in TrafficLevel}
        # Normalizing every step keeps numbers from underflowing on long sequences.
        belief = normalize({x: predicted[x] * hmm.emission[x][obs] for x in TrafficLevel})
    return belief
