"""Mergeable sample moments and honest normal-approximation uncertainty."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Hashable, Iterable, Mapping, Sequence


CI95_Z = 1.959963984540054

# Both merge paths refuse clustered input the same way (DEV-182, fix 2).
CLUSTERED_MERGE_REFUSAL = (
    "clustered moments cannot be merged without per-cluster totals; "
    "build one ClusteredSampleMoments.from_clustered_values over all "
    "observations and cluster labels instead"
)


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
        if any(isinstance(other, ClusteredSampleMoments) for other in others):
            raise NotImplementedError(CLUSTERED_MERGE_REFUSAL)
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

    def merge(self, *others: "SampleMoments") -> "ClusteredSampleMoments":
        """Reject a merge that cannot preserve cluster-level sufficient data."""
        raise NotImplementedError(CLUSTERED_MERGE_REFUSAL)

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


@dataclass(frozen=True)
class WeightedSampleMoments:
    """Self-normalized importance-sampling moments (simulation-math §2, §7).

    The equal-weight path keeps using `SampleMoments`. This class serves the
    weighted path, where `s/√N` is the wrong formula rather than a slightly
    optimistic one: the estimator is `x̄ = Σwᵢxᵢ / Σwᵢ`, so its variance is the
    self-normalized delta-method one, and swapping `N` for `N_eff` inside
    `s/√N` does not recover it.

    The seven sums below are sufficient for the estimate, the delta-method
    variance and the doc's weighted within-stratum variance, so weighted
    chunks merge exactly the way `SampleMoments` chunks do.
    """

    n: int = 0
    weight_sum: float = 0.0                # Σ wᵢ
    weight_square_sum: float = 0.0         # Σ wᵢ²
    weighted_sum: float = 0.0              # Σ wᵢ xᵢ
    weighted_sum_squares: float = 0.0      # Σ wᵢ xᵢ²
    square_weighted_sum: float = 0.0       # Σ wᵢ² xᵢ
    square_weighted_sum_squares: float = 0.0  # Σ wᵢ² xᵢ²

    @classmethod
    def from_values(
        cls,
        values: Iterable[float],
        weights: Iterable[float],
    ) -> "WeightedSampleMoments":
        items = tuple(values)
        w = tuple(weights)
        if len(items) != len(w):
            raise ValueError("values and weights must have the same length")
        if any(weight < 0.0 for weight in w):
            raise ValueError("importance weights must be non-negative")
        return cls(
            len(items),
            sum(w),
            sum(weight * weight for weight in w),
            sum(weight * value for weight, value in zip(w, items)),
            sum(weight * value * value for weight, value in zip(w, items)),
            sum(weight * weight * value for weight, value in zip(w, items)),
            sum(
                weight * weight * value * value
                for weight, value in zip(w, items)
            ),
        )

    def merge(self, *others: "WeightedSampleMoments") -> "WeightedSampleMoments":
        parts = (self,) + others
        return WeightedSampleMoments(
            sum(part.n for part in parts),
            sum(part.weight_sum for part in parts),
            sum(part.weight_square_sum for part in parts),
            sum(part.weighted_sum for part in parts),
            sum(part.weighted_sum_squares for part in parts),
            sum(part.square_weighted_sum for part in parts),
            sum(part.square_weighted_sum_squares for part in parts),
        )

    @property
    def mean(self) -> float:
        return 0.0 if not self.weight_sum else self.weighted_sum / self.weight_sum

    @property
    def effective_sample_size(self) -> float | None:
        """`N_eff` — a diagnostic of weight concentration, never a divisor.

        Reported alongside every weighted estimate, because `N` on its own
        stops describing how much information the sample carries once the
        weights are uneven.
        """
        if not self.weight_square_sum:
            return None
        return self.weight_sum * self.weight_sum / self.weight_square_sum

    @property
    def sample_variance(self) -> float | None:
        """Weighted variance of `X`, unbiased under reliability weights.

        `s² = [Σw ⁄ ((Σw)²−Σw²)] · Σ w (x−x̄)²`. With equal weights this is the
        ordinary `s²`, which is what makes it safe to use for Neyman
        allocation on either path.
        """
        denominator = self.weight_sum * self.weight_sum - self.weight_square_sum
        if self.n < 2 or denominator <= 0.0:
            return None
        return max(0.0, self.weight_sum * self._weighted_residual_sum / denominator)

    @property
    def variance(self) -> float | None:
        """Delta-method variance of the self-normalized mean.

        `V̂ar(x̄) = Σ wᵢ²(xᵢ−x̄)² ⁄ (Σwᵢ)²`, carrying the same `n ⁄ (n−1)`
        finite-sample correction the equal-weight path applies. That
        correction is what makes this degenerate exactly to `s²/N` when every
        weight is the same, rather than to the plug-in `((N−1)/N)·s²/N`.
        """
        if self.n < 2 or not self.weight_sum:
            return None
        plug_in = self._square_weighted_residual_sum / (self.weight_sum ** 2)
        return max(0.0, plug_in * self.n / (self.n - 1))

    @property
    def standard_error(self) -> float | None:
        variance = self.variance
        return None if variance is None else sqrt(variance)

    @property
    def _weighted_residual_sum(self) -> float:
        """`Σ wᵢ (xᵢ−x̄)²`, expanded so the sums stay mergeable."""
        mean = self.mean
        return (
            self.weighted_sum_squares
            - 2.0 * mean * self.weighted_sum
            + mean * mean * self.weight_sum
        )

    @property
    def _square_weighted_residual_sum(self) -> float:
        """`Σ wᵢ² (xᵢ−x̄)²`, expanded so the sums stay mergeable."""
        mean = self.mean
        return (
            self.square_weighted_sum_squares
            - 2.0 * mean * self.square_weighted_sum
            + mean * mean * self.weight_square_sum
        )


@dataclass(frozen=True)
class WeightedStrata:
    """Stratum weights read off the posterior, not off the proposal.

    `x̄_str = Σ_k π_k x̄_k` is only unbiased when `π_k` is the stratum
    probability under `π(H|ℐ)`. A pilot that counts how many uniformly drawn
    worlds landed in each stratum measures the proposal `q` instead, and the
    river-reading likelihood moves that occupancy a lot — worlds where somebody
    is waiting score much higher. So every quantity here is weight-based:
    `π̂_k = Σ_{i∈S_k} wᵢ ⁄ Σᵢ wᵢ`.
    """

    per_stratum: tuple[tuple[Hashable, WeightedSampleMoments], ...] = ()

    @classmethod
    def from_values(
        cls,
        values: Iterable[float],
        weights: Iterable[float],
        strata: Iterable[Hashable],
    ) -> "WeightedStrata":
        items = tuple(values)
        w = tuple(weights)
        labels = tuple(strata)
        if not len(items) == len(w) == len(labels):
            raise ValueError("values, weights and strata must have the same length")
        grouped: dict[Hashable, tuple[list[float], list[float]]] = {}
        for value, weight, label in zip(items, w, labels):
            bucket = grouped.setdefault(label, ([], []))
            bucket[0].append(value)
            bucket[1].append(weight)
        return cls(tuple(
            (label, WeightedSampleMoments.from_values(bucket[0], bucket[1]))
            for label, bucket in grouped.items()
        ))

    @property
    def weight_sum(self) -> float:
        return sum(moments.weight_sum for _, moments in self.per_stratum)

    @property
    def stratum_weights(self) -> dict[Hashable, float]:
        """`π̂_k`. With equal weights these are plain count proportions."""
        total = self.weight_sum
        if not total:
            return {label: 0.0 for label, _ in self.per_stratum}
        return {
            label: moments.weight_sum / total
            for label, moments in self.per_stratum
        }

    @property
    def stratified_mean(self) -> float:
        weights = self.stratum_weights
        return sum(
            weights[label] * moments.mean
            for label, moments in self.per_stratum
        )

    @property
    def effective_sample_sizes(self) -> dict[Hashable, float | None]:
        """Per-stratum `N_eff`, because weight collapse concentrates in one.

        A global `N_eff` that still looks healthy can hide a stratum carried
        by a single world, and that stratum is usually `k=0` — the one holding
        the variance.
        """
        return {
            label: moments.effective_sample_size
            for label, moments in self.per_stratum
        }

    def neyman_allocation(self, total: int) -> dict[Hashable, int]:
        """`n_k ∝ π_k · s_k`, with `s_k` the weighted within-stratum spread.

        Strata whose spread cannot be estimated yet fall back to their
        posterior weight alone, so a pilot too small to price one stratum
        still allocates it samples rather than starving it.
        """
        weights = self.stratum_weights
        shares: dict[Hashable, float] = {}
        for label, moments in self.per_stratum:
            variance = moments.sample_variance
            spread = 1.0 if variance is None else sqrt(variance)
            shares[label] = weights[label] * spread
        divisor = sum(shares.values())
        if not divisor:
            return {label: 0 for label, _ in self.per_stratum}
        return _largest_remainder(shares, divisor, total)


def _largest_remainder(
    shares: Mapping[Hashable, float],
    divisor: float,
    total: int,
) -> dict[Hashable, int]:
    """Apportion `total` across `shares` so the parts sum to `total` exactly."""
    exact = {label: share / divisor * total for label, share in shares.items()}
    allocation = {label: int(value) for label, value in exact.items()}
    remaining = total - sum(allocation.values())
    ranked = sorted(
        exact,
        key=lambda label: (exact[label] - allocation[label], shares[label]),
        reverse=True,
    )
    for label in ranked[:max(0, remaining)]:
        allocation[label] += 1
    return allocation


@dataclass(frozen=True)
class ControlVariateEstimate:
    """A control-variate mean whose `β̂` was fitted off the applied sample.

    Fitting `β̂ = Ĉov(X,C)/V̂ar(C)` and applying it to the same trials
    correlates `β̂` with `C−μ_C`, which leaves the estimator consistent but
    biased at `O(1/n)`. Splitting the sample is the cheaper of the two fixes
    the doc weighs, and unlike a jackknife the independence boundary is
    directly testable — hence the two index tuples.
    """

    beta: float
    fitting_indices: tuple[int, ...]
    applying_indices: tuple[int, ...]
    moments: SampleMoments

    @property
    def mean(self) -> float:
        return self.moments.mean

    @property
    def standard_error(self) -> float | None:
        return self.moments.standard_error


def split_sample_control_variate(
    values: Sequence[float],
    controls: Sequence[float],
    control_mean: float,
) -> ControlVariateEstimate:
    """Price `values` against a control whose true mean is `control_mean`.

    `control_mean` must be the expectation under the *same* measure the values
    were drawn from. That is why this takes the equal-weight path only: once
    §2's weighting is on, the actor's draw marginal is no longer uniform, `μ_C`
    is no longer §3's curve, and the whole construction shifts the estimate by
    `β(μ_C^true − μ_C^used)` — a shift that does not shrink with `N`.
    """
    if len(values) != len(controls):
        raise ValueError("values and controls must have the same length")
    split = len(values) // 2
    fitting = range(split)
    applying = range(split, len(values))
    beta = _fitted_beta(
        [values[i] for i in fitting],
        [controls[i] for i in fitting],
    )
    adjusted = [
        values[i] - beta * (controls[i] - control_mean)
        for i in applying
    ]
    return ControlVariateEstimate(
        beta,
        tuple(fitting),
        tuple(applying),
        SampleMoments.from_values(adjusted),
    )


def _fitted_beta(values: Sequence[float], controls: Sequence[float]) -> float:
    """`Ĉov(X,C)/V̂ar(C)`, or 0 where the control carries no signal."""
    n = len(values)
    if n < 2:
        return 0.0
    value_mean = sum(values) / n
    control_mean = sum(controls) / n
    variance = sum((c - control_mean) ** 2 for c in controls)
    if variance <= 0.0:
        return 0.0
    covariance = sum(
        (v - value_mean) * (c - control_mean)
        for v, c in zip(values, controls)
    )
    return covariance / variance


@dataclass(frozen=True)
class EventContribution:
    """One row of the terminal-event decomposition: `p̂(z)`, `m̂(z)`, `ĉ(z)`."""

    probability: float
    mean: float
    contribution: float


def decompose_by_event(
    trials: Iterable[Mapping[Hashable, tuple[float, float]]],
) -> dict[Hashable, EventContribution]:
    """Split net EV by terminal event so the parts add back to the whole.

    Each trial maps an event `z` to `(P(Z=z | Hᵢ,Uᵢ), (Δ_q + ΔV_q)(z,i))`. The
    payoff must already carry the continuation value: with `V ≢ 0` a
    decomposition of `Δ_q` alone no longer sums to net EV, and the gap is
    largest exactly where a player most wants the breakdown — an exhaustive
    draw, where keeping the dealership is most of the value.

    `Σ_z ĉ(z) = x̄` holds exactly only because `m̂(z)` pools the numerator and
    denominator across trials. Estimating each event's conditional mean as a
    separate marginal would not add back.
    """
    rows = tuple(trials)
    if not rows:
        return {}
    probability_totals: dict[Hashable, float] = {}
    payoff_totals: dict[Hashable, float] = {}
    for row in rows:
        for event, (probability, payoff) in row.items():
            probability_totals[event] = (
                probability_totals.get(event, 0.0) + probability
            )
            payoff_totals[event] = (
                payoff_totals.get(event, 0.0) + probability * payoff
            )
    n = len(rows)
    decomposition: dict[Hashable, EventContribution] = {}
    for event, probability_total in probability_totals.items():
        payoff_total = payoff_totals[event]
        mean = 0.0 if not probability_total else payoff_total / probability_total
        probability = probability_total / n
        # ĉ(z) is built as p̂(z)·m̂(z), the way the doc defines it, so that the
        # `Σ_z ĉ(z) = x̄` identity is a consequence of the pooled m̂ rather
        # than of a shortcut that would hold for any m̂ whatsoever.
        decomposition[event] = EventContribution(
            probability,
            mean,
            probability * mean,
        )
    return decomposition


def decomposed_net_ev(
    decomposition: Mapping[Hashable, EventContribution],
) -> float:
    """`Σ_z ĉ(z)`, which equals the plain mean of the per-trial payoffs."""
    return sum(row.contribution for row in decomposition.values())
