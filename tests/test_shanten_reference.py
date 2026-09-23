"""Check the production evaluator against the pre-optimization definition."""

import random

from taimahjong.shanten import _shanten_unchecked, _shanten_unchecked_reference


def test_random_legal_hands_match_frozen_reference():
    rng = random.Random(221)
    for melds in range(6):
        for size in (16 - 3 * melds, 17 - 3 * melds):
            for _ in range(500):
                counts = [0] * 34
                for _ in range(size):
                    tile = rng.choice([tile for tile, count in enumerate(counts)
                                       if count < 4])
                    counts[tile] += 1
                hand = tuple(counts)
                assert _shanten_unchecked(hand, melds) == _shanten_unchecked_reference(
                    hand, melds
                ), (hand, melds)
