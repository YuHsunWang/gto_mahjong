"""MJ-011 mergeable moments and paired EV uncertainty."""

from server import api
from taimahjong.ev import EVRankEntry, paired_delta_moments, ev_rank
from taimahjong.moments import SampleMoments
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
