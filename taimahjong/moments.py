"""Mergeable sample moments and honest normal-approximation uncertainty."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable


CI95_Z = 1.959963984540054


@dataclass(frozen=True)
class SampleMoments:
    """Sufficient statistics that merge exactly across seeded chunks."""

    n: int = 0
    total: float = 0.0
    sum_squares: float = 0.0
    post_selection: bool = False

    @classmethod
    def from_values(
        cls,
        values: Iterable[float],
        *,
        post_selection: bool = False,
    ) -> "SampleMoments":
        items = tuple(values)
        return cls(
            len(items),
            sum(items),
            sum(value * value for value in items),
            post_selection,
        )

    def merge(self, *others: "SampleMoments") -> "SampleMoments":
        return SampleMoments(
            self.n + sum(other.n for other in others),
            self.total + sum(other.total for other in others),
            self.sum_squares + sum(other.sum_squares for other in others),
            self.post_selection or any(other.post_selection for other in others),
        )

    @property
    def mean(self) -> float:
        return 0.0 if not self.n else self.total / self.n

    @property
    def sample_variance(self) -> float | None:
        if self.n < 2:
            return None
        numerator = self.sum_squares - self.total * self.total / self.n
        return max(0.0, numerator / (self.n - 1))

    @property
    def standard_error(self) -> float | None:
        variance = self.sample_variance
        return None if variance is None else sqrt(variance / self.n)

    @property
    def ci95(self) -> tuple[float, float] | None:
        standard_error = self.standard_error
        if standard_error is None:
            return None
        margin = CI95_Z * standard_error
        return self.mean - margin, self.mean + margin

    @property
    def ci95_low(self) -> float | None:
        interval = self.ci95
        return None if interval is None else interval[0]

    @property
    def ci95_high(self) -> float | None:
        interval = self.ci95
        return None if interval is None else interval[1]

    @property
    def crosses_zero(self) -> bool | None:
        interval = self.ci95
        if interval is None:
            # A selected top-gap with no estimable interval must remain
            # "uncertain" in callers that use this conservative boolean.
            return True if self.post_selection else None
        low, high = interval
        return low <= 0.0 <= high

    def payload(
        self,
        effect_size_threshold: float | None = None,
    ) -> dict[str, float | int | bool | list[float] | str]:
        payload: dict[str, float | int | bool | list[float] | str] = {
            "n": self.n,
            "sum": self.total,
            "sumsq": self.sum_squares,
            "mean": self.mean,
        }
        standard_error = self.standard_error
        interval = self.ci95
        if standard_error is not None:
            payload["se"] = standard_error
        if interval is not None:
            low, high = interval
            if self.post_selection:
                payload["descriptive_interval95"] = [low, high]
                payload["interval_note"] = (
                    "Paired descriptive interval after selecting the top two; "
                    "not a selection-adjusted 95% confidence interval."
                )
            else:
                payload["ci95"] = [low, high]
            payload["crosses_zero"] = low <= 0.0 <= high
        else:
            payload["uncertainty"] = "unavailable: fewer than two samples"
        if effect_size_threshold is not None:
            effect_small = abs(self.mean) < effect_size_threshold
            payload.update({
                "effect_threshold": effect_size_threshold,
                "effect_small": effect_small,
                "wording": (
                    "uncertain"
                    if self.crosses_zero is not False
                    else "marginal"
                    if effect_small
                    else "clear"
                ),
            })
        return payload


@dataclass(frozen=True)
class ClusteredSampleMoments(SampleMoments):
    """Moments whose sampling error is estimated from independent clusters."""

    cluster_count: int = 0
    cluster_score_sum_squares: float = 0.0

    @classmethod
    def from_clustered_values(
        cls,
        values: Iterable[float],
        clusters: Iterable[int],
        *,
        post_selection: bool = False,
    ) -> "ClusteredSampleMoments":
        items = tuple(values)
        labels = tuple(clusters)
        if len(items) != len(labels):
            raise ValueError("values and clusters must have the same length")
        totals: dict[int, float] = {}
        counts: dict[int, int] = {}
        for value, cluster in zip(items, labels):
            totals[cluster] = totals.get(cluster, 0.0) + value
            counts[cluster] = counts.get(cluster, 0) + 1
        mean = 0.0 if not items else sum(items) / len(items)
        score_sum_squares = sum(
            (total - counts[cluster] * mean) ** 2
            for cluster, total in totals.items()
        )
        return cls(
            len(items),
            sum(items),
            sum(value * value for value in items),
            post_selection,
            len(totals),
            score_sum_squares,
        )

    @property
    def standard_error(self) -> float | None:
        if self.cluster_count < 2 or not self.n:
            return None
        variance = (
            self.cluster_count
            / (self.cluster_count - 1)
            * self.cluster_score_sum_squares
            / (self.n * self.n)
        )
        return sqrt(max(0.0, variance))
