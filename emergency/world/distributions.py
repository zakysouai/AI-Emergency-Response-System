"""Small helpers for discrete probability distributions stored as dicts."""

from __future__ import annotations

from typing import Hashable, Mapping, TypeVar

K = TypeVar("K", bound=Hashable)


def normalize(weights: Mapping[K, float]) -> dict[K, float]:
    """Scale non-negative weights so they sum to 1 (the α in α·P(...))."""
    total = sum(weights.values())
    if total <= 0:
        # Only happens when the evidence has probability 0 under the model.
        raise ValueError("cannot normalize: all weights are zero")
    return {key: w / total for key, w in weights.items()}


def expected_value(dist: Mapping[K, float], values: Mapping[K, float]) -> float:
    """E[f(X)] = Σ_x P(x)·f(x)."""
    return sum(p * values[key] for key, p in dist.items())
