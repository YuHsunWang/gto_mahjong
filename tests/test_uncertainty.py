"""MJ-011 mergeable moments and paired EV uncertainty."""

import pytest

from server import api
from taimahjong.ev import EVRankEntry, paired_delta_moments, ev_rank
from taimahjong.moments import ClusteredSampleMoments, SampleMoments
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
