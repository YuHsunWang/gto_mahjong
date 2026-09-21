"""MJ-011 mergeable moments and paired EV uncertainty."""

import pytest

from server import api
from taimahjong.ev import EVRankEntry, paired_delta_moments, ev_rank
from taimahjong.moments import (
    ClusteredSampleMoments,
    SampleMoments,
    WeightedSampleMoments,
    WeightedStrata,
    decompose_by_event,
    decomposed_net_ev,
    split_sample_control_variate,
)
from taimahjong.quiz import QuizGrade
from taimahjong.selfplay import head_to_head
from taimahjong.tiles import parse_tiles


def test_chunk_merged_mean_and_se_equal_single_run():
    values = (3.0, -1.0, 7.0, 2.0, -4.0, 5.0)
    single = SampleMoments.from_values(values)
    merged = SampleMoments.from_values(values[:2]).merge(
        SampleMoments.from_values(values[2:5]),
        SampleMoments.from_values(values[5:]),
    )

    assert merged == single
    assert merged.mean == single.mean
    assert merged.standard_error == single.standard_error


def test_clustered_se_does_not_treat_reused_hidden_worlds_as_independent():
    values = (0.0, 10.0) * 100
    clusters = (0, 1) * 100

    independent = SampleMoments.from_values(values)
    clustered = ClusteredSampleMoments.from_clustered_values(values, clusters)

    assert clustered.mean == independent.mean == 5.0
    assert clustered.standard_error == 5.0
    assert clustered.standard_error > 10 * independent.standard_error


def test_head_to_head_seed_chunks_merge_to_single_run_se():
    single = head_to_head(4, 9200)
    left = head_to_head(2, 9200)
    right = head_to_head(2, 9202)

    def moments(result):
        return SampleMoments.from_values(
            ev_points - attack_points
            for ev_points, attack_points in result.game_deltas
        )

    merged = moments(left).merge(moments(right))
    assert merged == moments(single)
    assert merged.standard_error == single.standard_error


def test_ev_entries_expose_moments_ci_and_paired_top_gap():
    ranked = [
        entry for entry in ev_rank(
            parse_tiles("123456789m11234p567s"),
            (), (0,) * 34, turns=2, sims=12, seed=91, exhaustive=True,
        )
        if not entry.is_fold
    ]
    ranked.sort(key=lambda entry: (-entry.net_ev, entry.discard))
    gap = paired_delta_moments(ranked[0], ranked[1])

    assert all(entry.sample_count == 12 for entry in ranked)
    assert all(entry.win_count <= entry.sample_count for entry in ranked)
    assert all(entry.ci95_low <= entry.net_ev <= entry.ci95_high for entry in ranked)
    assert gap.n == 12
    assert gap.ci95_low <= gap.mean <= gap.ci95_high


def test_boundary_top_gap_whose_paired_ci_crosses_zero_is_uncertain():
    first = EVRankEntry(
        0, 0.0, None, 0.0, (), 0.0, 0.1,
        sample_count=4, trial_values=(1.0, -1.0, 1.0, -0.6),
    )
    second = EVRankEntry(
        1, 0.0, None, 0.0, (), 0.0, 0.0,
        sample_count=4, trial_values=(0.0, 0.0, 0.0, 0.0),
    )

    payload = api._top_gap_payload([first, second])

    assert payload is not None
    assert payload["crosses_zero"] is True
    assert payload["wording"] == "uncertain"
    assert "ci95" not in payload
    assert len(payload["descriptive_interval95"]) == 2
    assert "not a selection-adjusted" in payload["interval_note"]


@pytest.mark.parametrize(("values", "state"), [
    ((-0.1, 0.1, -0.1, 0.1), "uncertain"),
    ((0.05, 0.05, 0.05, 0.05), "marginal"),
    ((0.2, 0.2, 0.2, 0.2), "clear"),
])
def test_quiz_grade_owns_the_ranking_state_consumed_by_clients(values, state):
    grade = QuizGrade(
        position=None, best=None, chosen=None, ranked=(), ev_delta=0.0,
        rank_position=1, verdict="best",
        top_gap=SampleMoments.from_values(values, post_selection=True),
    )

    assert grade.ranking_state == state
    assert grade.ranking_uncertain is (state != "clear")


def test_single_sample_never_emits_a_zero_width_95_percent_ci():
    moments = SampleMoments.from_values((0.0,))
    payload = moments.payload()

    assert moments.sample_variance is None
    assert moments.standard_error is None
    assert moments.ci95 is None
    assert "ci95" not in payload
    assert payload["uncertainty"] == "unavailable: fewer than two samples"

    response = api.ev_rank_endpoint(api.EvRankRequest(
        hand="123456789m11234p567s",
        turns=1,
        sims=1,
        seed=77,
        exhaustive=True,
    ))
    assert all(entry["ci95"] == [None, None] for entry in response["entries"])
    assert "ci95" not in response["top1_vs_top2"]
    assert response["top1_vs_top2"]["uncertainty"].startswith("unavailable")
    assert response["top1_vs_top2"]["wording"] == "uncertain"


def test_stateless_ev_response_adds_ci_paired_gap_and_candidate_scope():
    response = api.ev_rank_endpoint(api.EvRankRequest(
        hand="123456789m11234p567s",
        turns=2,
        sims=4,
        seed=77,
        exhaustive=True,
    ))

    assert response["exhaustive"] is True
    assert response["candidate_scope"] == "all_legal_discards"
    assert response["top1_vs_top2"]["n"] == 4
    assert all(entry["sample_count"] == 4 for entry in response["entries"])
    assert all(len(entry["ci95"]) == 2 for entry in response["entries"])


def test_screening_pilot_draws_worlds_the_reported_sample_never_sees(monkeypatch):
    # A trial that helped eliminate a candidate must not also help price the
    # survivor, or the reported interval is a post-selection one.  The two
    # phases therefore build two CRN bases from two different seeds.
    import taimahjong.ev as ev_module

    seeds = []
    original = ev_module._production_worlds

    def recording(*args, **kwargs):
        seeds.append(args[5])
        return original(*args, **kwargs)

    monkeypatch.setattr(ev_module, "_production_worlds", recording)
    ev_rank(
        parse_tiles("123456789m11234p567s"),
        (), (0,) * 34, turns=2, sims=8, seed=23, top_k=2,
    )

    assert len(seeds) == 2
    assert seeds[0] != seeds[1]


def test_exhaustive_ranking_needs_no_pilot_and_builds_one_base(monkeypatch):
    import taimahjong.ev as ev_module

    seeds = []
    original = ev_module._production_worlds

    def recording(*args, **kwargs):
        seeds.append(args[5])
        return original(*args, **kwargs)

    monkeypatch.setattr(ev_module, "_production_worlds", recording)
    ev_rank(
        parse_tiles("123456789m11234p567s"),
        (), (0,) * 34, turns=2, sims=8, seed=23, exhaustive=True,
    )

    assert seeds == [23]


# --- Weighted estimators (simulation-math §2, §4.3, §6, §7) ------------------
#
# None of these are wired into production yet: §2's importance weighting is
# still unimplemented, so `ev.py` runs entirely on the equal-weight path. They
# exist so that the weighted path starts from the formulas the document
# actually ruled on, instead of the equal-weight ones wearing a t quantile.


def test_weighted_se_degenerates_to_s_over_root_n_when_weights_are_equal():
    # The weighted path must be a strict generalisation: if it disagreed with
    # `s/√N` on an equal-weight sample, every existing calibrated number would
    # shift the day importance weighting is switched on.
    values = (3.0, -1.0, 7.0, 2.0, -4.0, 5.0)

    equal = SampleMoments.from_values(values)
    weighted = WeightedSampleMoments.from_values(values, (2.5,) * len(values))

    assert weighted.mean == pytest.approx(equal.mean)
    assert weighted.sample_variance == pytest.approx(equal.sample_variance)
    assert weighted.standard_error == pytest.approx(equal.standard_error)
    assert weighted.effective_sample_size == pytest.approx(len(values))


def test_weighted_se_exceeds_the_equal_weight_formula_when_weight_concentrates():
    # Half the posterior mass sits on the single world that settles non-zero,
    # which is the realistic shape: the high-likelihood worlds are the ones
    # where somebody is tenpai, and those are the ones that cost points. The
    # equal-weight formula reports 1.67 for a sample worth 3.0.
    values = (0.0, 0.0, 0.0, 0.0, 0.0, 10.0)
    weights = (1.0, 1.0, 1.0, 1.0, 1.0, 5.0)

    equal = SampleMoments.from_values(values)
    weighted = WeightedSampleMoments.from_values(values, weights)

    assert weighted.mean == pytest.approx(5.0)
    assert weighted.standard_error == pytest.approx(3.0)
    assert equal.standard_error == pytest.approx(1.6666666666666667)
    assert weighted.effective_sample_size == pytest.approx(10 / 3)
    # N_eff is a diagnostic, not a divisor. Substituting it into `s/√N` gives
    # 2.24 here — closer than 1.67, and still the wrong number.
    assert weighted.standard_error != pytest.approx(
        equal.sample_variance ** 0.5 / weighted.effective_sample_size ** 0.5
    )


def test_weighted_chunks_merge_exactly_like_equal_weight_chunks():
    # Seeded chunks are merged all over this repo; a weighted estimator that
    # only worked on a single batch would silently break that pattern.
    values = (3.0, -1.0, 7.0, 2.0, -4.0, 5.0)
    weights = (0.5, 2.0, 1.25, 3.0, 0.75, 1.0)

    single = WeightedSampleMoments.from_values(values, weights)
    merged = WeightedSampleMoments.from_values(values[:2], weights[:2]).merge(
        WeightedSampleMoments.from_values(values[2:5], weights[2:5]),
        WeightedSampleMoments.from_values(values[5:], weights[5:]),
    )

    assert merged == single
    assert merged.standard_error == pytest.approx(single.standard_error)


def test_posterior_stratum_weights_degenerate_to_count_proportions():
    # Equal weights mean the proposal already is the posterior, so the
    # weighted estimator has to reproduce the plain occupancy counts.
    values = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    strata = (0, 0, 0, 1, 1, 2)

    strata_moments = WeightedStrata.from_values(values, (1.0,) * 6, strata)

    assert strata_moments.stratum_weights == {
        0: pytest.approx(0.5), 1: pytest.approx(1 / 3), 2: pytest.approx(1 / 6),
    }
    assert strata_moments.stratified_mean == pytest.approx(sum(values) / 6)


def test_river_reading_moves_stratum_weight_away_from_the_uniform_count():
    # The whole point of DEV-154: counting uniformly drawn worlds measures the
    # proposal `q`, not the posterior. Worlds where somebody is close to a win
    # score a higher likelihood, so `k=0` must gain weight over its raw count.
    # A pilot that estimated `π_k` by counting would under-weight exactly the
    # stratum that carries the variance.
    values = (10.0, 10.0, 0.0, 0.0, 0.0, 0.0)
    strata = (0, 0, 1, 1, 1, 1)
    likelihood = (9.0, 9.0, 1.0, 1.0, 1.0, 1.0)

    counted = WeightedStrata.from_values(values, (1.0,) * 6, strata)
    posterior = WeightedStrata.from_values(values, likelihood, strata)

    assert counted.stratum_weights[0] == pytest.approx(1 / 3)
    assert posterior.stratum_weights[0] == pytest.approx(18 / 22)
    assert posterior.stratified_mean > counted.stratified_mean


def test_neyman_allocation_follows_posterior_weight_times_spread():
    # Neyman sends samples where `π_k · s_k` is large. A stratum that is rare
    # but wild must still outrank a common flat one, or the allocation just
    # reproduces the occupancy counts.
    values = (0.0, 20.0, 0.0, 20.0, 5.0, 5.0, 5.0, 5.0)
    strata = ("wild", "wild", "wild", "wild", "flat", "flat", "flat", "flat")
    weights = (1.0, 1.0, 1.0, 1.0, 3.0, 3.0, 3.0, 3.0)

    allocation = WeightedStrata.from_values(
        values, weights, strata,
    ).neyman_allocation(100)

    assert sum(allocation.values()) == 100
    # "flat" holds three quarters of the posterior weight but has zero spread,
    # so every sample goes to the stratum that actually carries variance.
    assert allocation["wild"] == 100
    assert allocation["flat"] == 0


def test_weighted_within_stratum_variance_is_the_ordinary_s2_on_equal_weights():
    # Neyman allocation reads `s_k` off this quantity on both paths, so the
    # weighted formula has to agree with the equal-weight one where they meet.
    values = (4.0, 8.0, 15.0, 16.0, 23.0, 42.0)

    weighted = WeightedSampleMoments.from_values(values, (7.0,) * len(values))

    assert weighted.sample_variance == pytest.approx(
        SampleMoments.from_values(values).sample_variance
    )


def test_control_variate_fits_beta_on_trials_it_never_prices():
    # Fitting β̂ and applying it to the same trials correlates β̂ with C−μ_C
    # and biases the estimator at O(1/n). The split is the whole mechanism,
    # so the two index sets overlapping is the one thing worth asserting.
    values = [float(i % 5) for i in range(20)]
    controls = [float(i % 3) for i in range(20)]

    estimate = split_sample_control_variate(values, controls, control_mean=1.0)

    assert set(estimate.fitting_indices).isdisjoint(estimate.applying_indices)
    assert estimate.moments.n == len(estimate.applying_indices)
    assert len(estimate.fitting_indices) + len(estimate.applying_indices) == 20


def test_control_variate_with_a_known_mu_c_agrees_with_the_plain_estimator():
    # With the true μ_C the control variate must not move the answer, only
    # tighten it. A μ_C taken from the wrong measure would show up here as a
    # mean sitting outside the plain estimator's interval.
    import random

    rng = random.Random(4013)
    control_mean = 0.4
    controls = [1.0 if rng.random() < control_mean else 0.0 for _ in range(400)]
    values = [6.0 * c + rng.gauss(0.0, 1.0) for c in controls]

    estimate = split_sample_control_variate(values, controls, control_mean)
    priced = values[len(values) // 2:]
    plain = SampleMoments.from_values(priced)

    low, high = plain.ci95
    assert low <= estimate.mean <= high
    # Correlated control, so it has to buy something; otherwise the split cost
    # half the sample for nothing.
    assert estimate.standard_error < plain.standard_error


def test_event_decomposition_sums_back_to_net_ev_without_continuation_value():
    # `Σ_z ĉ(z) = x̄` is the property the output columns are sold on: a player
    # reading "deal-in rate × mean loss" must be able to add the rows up.
    trials = [
        {"tsumo": (0.3, 12.0), "ron": (0.2, -20.0), "draw": (0.5, 0.0)},
        {"tsumo": (0.1, 9.0), "ron": (0.4, -16.0), "draw": (0.5, 0.0)},
        {"tsumo": (0.5, 15.0), "ron": (0.1, -24.0), "draw": (0.4, 0.0)},
    ]

    decomposition = decompose_by_event(trials)
    net = sum(
        sum(p * payoff for p, payoff in row.values()) for row in trials
    ) / len(trials)

    assert abs(decomposed_net_ev(decomposition) - net) < 1e-9
    assert decomposition["draw"].contribution == pytest.approx(0.0)


def test_event_decomposition_still_sums_back_once_continuation_value_is_on():
    # With V ≢ 0 the draw row stops being zero — keeping the dealership is
    # worth something — and a decomposition of Δ alone would leave the rows
    # short of net EV by exactly that amount.
    trials = [
        {"tsumo": (0.3, 12.0 + 1.5), "ron": (0.2, -20.0 - 0.5), "draw": (0.5, 4.0)},
        {"tsumo": (0.1, 9.0 + 1.5), "ron": (0.4, -16.0 - 0.5), "draw": (0.5, 4.0)},
        {"tsumo": (0.5, 15.0 + 1.5), "ron": (0.1, -24.0 - 0.5), "draw": (0.4, 4.0)},
    ]

    decomposition = decompose_by_event(trials)
    net = sum(
        sum(p * payoff for p, payoff in row.values()) for row in trials
    ) / len(trials)

    assert abs(decomposed_net_ev(decomposition) - net) < 1e-9
    assert decomposition["draw"].contribution > 0.0


def test_event_means_pool_across_trials_rather_than_averaging_marginals():
    # The identity only holds for the pooled m̂(z). Averaging each trial's
    # conditional mean gives a different number whenever the event
    # probabilities differ between trials, and then the rows stop adding up.
    trials = [
        {"ron": (0.9, -10.0), "tsumo": (0.1, 30.0)},
        {"ron": (0.1, -30.0), "tsumo": (0.9, 10.0)},
    ]

    pooled = decompose_by_event(trials)["ron"].mean
    naive = (-10.0 + -30.0) / 2

    assert pooled == pytest.approx((0.9 * -10.0 + 0.1 * -30.0) / 1.0)
    assert pooled != pytest.approx(naive)
