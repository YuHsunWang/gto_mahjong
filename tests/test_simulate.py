"""Tests for self-draw Monte Carlo simulation."""

from math import comb
import random

import pytest

from taimahjong.simulate import _greedy_discard, win_probability, winning_trials
from taimahjong.tiles import format_tiles, parse_tiles
from taimahjong.ukeire import discard_analysis


TENPAI_HAND = parse_tiles("123m123p123s1112223z")


def _stand_pat_visible() -> tuple[int, ...]:
    """Leave three winning 3z tiles and one copy of each harmless decoy."""
    visible = [4 - count for count in TENPAI_HAND]
    visible[29] = 0  # 3z is the only winning kind, with three copies unseen.
    for tile in (4, 5, 6, 7, 8, 10, 11, 13, 14, 15, 16, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28, 30, 31, 32, 33):
        visible[tile] -= 1
    return tuple(visible)


def test_seeded_simulation_is_deterministic_and_seeds_vary():
    visible = _stand_pat_visible()
    first = win_probability(TENPAI_HAND, turns=5, visible=visible, sims=1000, seed=17)
    assert first == win_probability(TENPAI_HAND, turns=5, visible=visible, sims=1000, seed=17)
    assert first != win_probability(TENPAI_HAND, turns=5, visible=visible, sims=1000, seed=18)


def test_cumulative_curves_are_monotonic_and_wins_imply_tenpai():
    result = win_probability(TENPAI_HAND, turns=6, visible=_stand_pat_visible(), sims=1000, seed=8)
    assert result.tenpai_by_turn == sorted(result.tenpai_by_turn)
    assert result.win_by_turn == sorted(result.win_by_turn)
    assert all(win <= tenpai for tenpai, win in zip(result.tenpai_by_turn, result.win_by_turn))


def test_starting_tenpai_is_folded_into_turn_one_and_dead_wait_cannot_win():
    result = win_probability(TENPAI_HAND, turns=1, visible=parse_tiles("333z"), sims=100, seed=1)
    assert result.tenpai_by_turn == [1.0]
    assert result.p_tenpai == 1.0
    assert result.win_by_turn == [0.0]
    assert result.p_win == 0.0


def test_tenpai_stands_pat_and_matches_hypergeometric_self_draw_probability():
    visible = _stand_pat_visible()
    decoys = [tile for tile in range(34) if 4 - TENPAI_HAND[tile] - visible[tile] == 1]
    for tile in decoys:
        drawn = list(TENPAI_HAND)
        drawn[tile] += 1
        # This proves the fixed greedy policy restores the same tenpai hand
        # after every non-winning draw, so the wall calculation is exact.
        assert discard_analysis(tuple(drawn), visible=visible)[0].discard == tile

    turns = 5
    unseen_total = sum(4 - hand_count - seen_count for hand_count, seen_count in zip(TENPAI_HAND, visible))
    winning_tiles = 3
    expected = 1 - comb(unseen_total - winning_tiles, turns) / comb(unseen_total, turns)
    result = win_probability(TENPAI_HAND, turns=turns, visible=visible, sims=20_000, seed=42)
    assert abs(result.p_win - expected) <= 0.02


def test_rejects_invalid_turn_count_and_insufficient_pool():
    with pytest.raises(ValueError, match="turns"):
        win_probability(TENPAI_HAND, turns=0)

    exhausted_visible = tuple(4 - count for count in TENPAI_HAND)
    with pytest.raises(ValueError, match="unseen pool"):
        win_probability(TENPAI_HAND, turns=1, visible=exhausted_visible)


def test_dynamic_remaining_counts_resolve_review_seed_policy_divergence():
    """MJ-003 reproduction: turn 10 must use prior draws/discards, not initial seen."""
    initial = parse_tiles("123456789m1123p567s")
    remaining = [4 - count for count in initial]
    draws = [tile for tile, copies in enumerate(remaining) for _ in range(copies)]
    random.Random(1).shuffle(draws)
    current = initial
    prior_discards = []
    for turn, draw in enumerate(draws[:10], start=1):
        remaining[draw] -= 1
        post_draw = list(current)
        post_draw[draw] += 1
        current = tuple(post_draw)
        discard, _ = _greedy_discard(current, tuple(remaining), 0)
        if turn == 10:
            assert format_tiles(current) == "22344567789m234p567s"
            assert prior_discards == [33, 9, 24, 26, 20, 13, 0, 23, 9]
            dynamic_visible = [0] * 34
            for prior in prior_discards:
                dynamic_visible[prior] += 1
            assert discard_analysis(current, visible=(0,) * 34)[0].discard == 1
            assert discard_analysis(current, visible=tuple(dynamic_visible))[0].discard == 3
            assert discard == 3  # 4m; stale initial-visible accounting chose 2m
            break
        reduced = list(current)
        reduced[discard] -= 1
        current = tuple(reduced)
        prior_discards.append(discard)


def test_win_probability_is_exactly_the_aggregate_of_shared_winning_trials():
    visible = _stand_pat_visible()
    kwargs = dict(turns=6, visible=visible, sims=240, seed=73)
    result = win_probability(TENPAI_HAND, **kwargs)
    wins = winning_trials(TENPAI_HAND, **kwargs)
    assert result.p_win == len(wins) / kwargs["sims"]
    assert result.win_by_turn == [
        sum(win.turn <= turn for win in wins) / kwargs["sims"]
        for turn in range(1, kwargs["turns"] + 1)
    ]
