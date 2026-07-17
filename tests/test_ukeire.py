import random

import pytest

from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles
from taimahjong.ukeire import discard_analysis, ukeire


def _random_hand(rng, size):
    wall = [tile for tile in range(34) for _ in range(4)]
    return tuple(wall.pop(rng.randrange(len(wall))) for _ in range(size))


def _counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile] += 1
    return tuple(counts)


def test_tenpai_ukeire_lists_its_winning_tile():
    hand = parse_tiles("123m123p123s1112223z")
    assert shanten(hand) == 0
    assert ukeire(hand) == {29: 3}


def test_one_shanten_ukeire_has_known_acceptance_set():
    hand = parse_tiles("123m123p123s1112234z")
    assert shanten(hand) == 1
    assert ukeire(hand) == {28: 2, 29: 3, 30: 3}


def test_visible_tiles_reduce_unseen_count_and_keep_zero_waits():
    hand = parse_tiles("123m123p123s1112223z")
    visible = parse_tiles("333z")
    assert ukeire(hand, visible=visible) == {29: 0}


def test_ukeire_supports_declared_melds():
    hand = parse_tiles("123m123p123s1112z")
    assert ukeire(hand, melds_declared=1) == {28: 3}


def test_visible_and_hand_cannot_exceed_four_copies():
    hand = parse_tiles("123m123p123s1112223z")
    with pytest.raises(ValueError, match="more than four"):
        ukeire(hand, visible=parse_tiles("3333z"))


def test_ukeire_matches_independent_per_draw_shanten_over_seeded_hands():
    rng = random.Random(20260717)
    for _ in range(120):
        hand = _counts(_random_hand(rng, 16))
        current = shanten(hand)
        accepted = ukeire(hand)
        for tile, count in enumerate(hand):
            if count == 4:
                assert tile not in accepted
                continue
            drawn = list(hand)
            drawn[tile] += 1
            improves = shanten(tuple(drawn)) < current
            assert (tile in accepted) is improves


def test_discard_analysis_is_ranked_and_matches_post_discard_ukeire():
    rng = random.Random(20260718)
    for _ in range(120):
        hand = _counts(_random_hand(rng, 17))
        analyses = discard_analysis(hand)
        assert analyses[0].shanten_after == min(entry.shanten_after for entry in analyses)
        for entry in analyses:
            post_discard = list(hand)
            post_discard[entry.discard] -= 1
            assert entry.ukeire == ukeire(tuple(post_discard))
            assert entry.total == sum(entry.ukeire.values())
