"""Tests for self-draw Monte Carlo simulation."""

from math import comb
import random

import pytest

from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2, WinContext, score_hand
from taimahjong.shanten import shanten
from taimahjong.simulate import _greedy_discard, win_probability, winning_trials
from taimahjong.tiles import format_tiles, parse_tiles
from taimahjong.ukeire import discard_analysis


TENPAI_HAND = parse_tiles("123m123p123s1112223z")


def _unweighted_reference_discard(
    current: tuple[int, ...], remaining_counts: tuple[int, ...], melds_declared: int,
) -> tuple[int, int]:
    """Reproduce the pre-DEV-157 discard rule for degeneracy checks."""
    candidates = []
    best_shanten = 11
    for tile, count in enumerate(current):
        if not count:
            continue
        after = list(current)
        after[tile] -= 1
        after_shanten = shanten(tuple(after), melds_declared)
        if after_shanten < best_shanten:
            best_shanten = after_shanten
            candidates = [(tile, tuple(after))]
        elif after_shanten == best_shanten:
            candidates.append((tile, tuple(after)))

    ranked = []
    for tile, after in candidates:
        accepted = 0
        for draw, copies in enumerate(remaining_counts):
            completed = list(after)
            completed[draw] += 1
            if copies > 0 and shanten(tuple(completed), melds_declared) < best_shanten:
                accepted += copies
        ranked.append((-accepted, tile))
    return min(ranked)[1], best_shanten


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


def test_value_weighting_degenerates_to_ukeire_for_none_and_constant_tai():
    rng = random.Random(157)
    wall = [tile for tile in range(34) for _ in range(4)]

    def constant_tai(_hand, _winning_tile):
        return 4

    for _ in range(200):
        rng.shuffle(wall)
        current = tuple(wall[:17].count(tile) for tile in range(34))
        remaining = tuple(rng.randint(0, 4 - count) for count in current)
        expected = _unweighted_reference_discard(current, remaining, 0)
        assert _greedy_discard(current, remaining, 0) == expected
        assert _greedy_discard(current, remaining, 0, SCHEME_3_1, constant_tai) == expected
        assert _greedy_discard(current, remaining, 0, SCHEME_5_2, constant_tai) == expected


def test_value_weighting_prefers_narrow_high_tai_wait_as_ratio_increases():
    current = parse_tiles("33345777m333667778s")
    remaining = (
        2, 4, 0, 2, 1, 3, 1, 2, 4, 4, 1, 1, 0, 3, 3, 2, 4,
        2, 2, 0, 1, 4, 3, 0, 0, 3, 2, 4, 2, 1, 2, 3, 2, 1,
    )

    def accepted_values(discard):
        after = list(current)
        after[discard] -= 1
        values = []
        for draw, copies in enumerate(remaining):
            completed = list(after)
            completed[draw] += 1
            if copies and shanten(tuple(completed)) == -1:
                result = score_hand(
                    tuple(completed),
                    context=WinContext(winning_tile=draw, self_draw=True),
                )
                values.append((copies, result))
        return values

    wide = accepted_values(24)  # discard 7s: six copies, all worth 2 tai
    narrow = accepted_values(25)  # discard 8s: three copies worth 7 tai
    assert (
        sum(copies for copies, _ in wide),
        {result.total_tai for _, result in wide},
    ) == (6, {2})
    assert (
        sum(copies for copies, _ in narrow),
        {result.total_tai for _, result in narrow},
    ) == (3, {7})
    assert sum(copies * result.value_in(SCHEME_3_1) for copies, result in wide) == 30
    assert sum(copies * result.value_in(SCHEME_3_1) for copies, result in narrow) == 30
    assert sum(copies * result.value_in(SCHEME_5_2) for copies, result in wide) == 54
    assert sum(copies * result.value_in(SCHEME_5_2) for copies, result in narrow) == 57

    _greedy_discard.cache_clear()
    assert _greedy_discard(current, remaining, 0) == (24, 0)
    assert _greedy_discard(current, remaining, 0, SCHEME_3_1) == (24, 0)
    assert _greedy_discard(current, remaining, 0, SCHEME_5_2) == (25, 0)


def test_declared_melds_remain_unweighted_without_their_tiles():
    current = parse_tiles("123456789m11234p")
    remaining = tuple(4 - count for count in current)

    def unexpected_estimate(_hand, _winning_tile):
        raise AssertionError("declared hands cannot be scored without meld tiles")

    assert _greedy_discard(current, remaining, 1, SCHEME_5_2, unexpected_estimate) == _greedy_discard(
        current, remaining, 1,
    )


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
