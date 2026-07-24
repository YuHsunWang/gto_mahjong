"""Mergeable sample moments and normal-approximation uncertainty."""

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

    @classmethod
    def from_values(cls, values: Iterable[float]) -> "SampleMoments":
        items = tuple(values)
        return cls(
            len(items),
            sum(items),
            sum(value * value for value in items),
        )

    def merge(self, *others: "SampleMoments") -> "SampleMoments":
        return SampleMoments(
            self.n + sum(other.n for other in others),
            self.total + sum(other.total for other in others),
            self.sum_squares + sum(other.sum_squares for other in others),
        )

    @property
    def mean(self) -> float:
        return 0.0 if not self.n else self.total / self.n

    @property
    def sample_variance(self) -> float:
        if self.n < 2:
            return 0.0
        numerator = self.sum_squares - self.total * self.total / self.n
        return max(0.0, numerator / (self.n - 1))

    @property
    def standard_error(self) -> float:
        return 0.0 if not self.n else sqrt(self.sample_variance / self.n)

    @property
    def ci95(self) -> tuple[float, float]:
        margin = CI95_Z * self.standard_error
        return self.mean - margin, self.mean + margin

    @property
    def ci95_low(self) -> float:
        return self.ci95[0]

    @property
    def ci95_high(self) -> float:
        return self.ci95[1]

    @property
    def crosses_zero(self) -> bool:
        low, high = self.ci95
        return low <= 0.0 <= high

    def payload(
        self,
        effect_size_threshold: float | None = None,
    ) -> dict[str, float | int | bool | list[float] | str]:
        low, high = self.ci95
        payload: dict[str, float | int | bool | list[float] | str] = {
            "n": self.n,
            "sum": self.total,
            "sumsq": self.sum_squares,
            "mean": self.mean,
            "se": self.standard_error,
            "ci95": [low, high],
            "crosses_zero": self.crosses_zero,
        }
        if effect_size_threshold is not None:
            effect_small = abs(self.mean) < effect_size_threshold
            payload.update({
                "effect_threshold": effect_size_threshold,
                "effect_small": effect_small,
                "wording": (
                    "uncertain"
                    if self.crosses_zero
                    else "marginal"
                    if effect_small
                    else "clear"
                ),
            })
        return payload
