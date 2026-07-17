"""Cross-validate the optimized decomposition against exchange search."""

import random

from taimahjong.bruteforce import bruteforce_shanten
from taimahjong.shanten import shanten


def _random_meld(rng):
    if rng.randrange(2):
        tile = rng.randrange(34)
        return (tile, tile, tile)
    suit = rng.randrange(3)
    start = rng.randrange(7)
    tile = suit * 9 + start
    return (tile, tile + 1, tile + 2)


def _winning_concealed_hand(rng, declared_melds):
    """Make a legal concealed part of a regular winning hand."""
    remaining_melds = 5 - declared_melds
    while True:
        counts = [0] * 34
        components = [_random_meld(rng) for _ in range(remaining_melds)]
        pair_tile = rng.randrange(34)
        for component in components:
            for tile in component:
                counts[tile] += 1
        counts[pair_tile] += 2
        if max(counts) <= 4:
            return counts


def _exchange_in_place(rng, counts):
    removable = [tile for tile, count in enumerate(counts) if count]
    removed = rng.choice(removable)
    counts[removed] -= 1
    addable = [tile for tile, count in enumerate(counts) if count < 4 and tile != removed]
    counts[rng.choice(addable)] += 1


def _random_realistic_hand(rng):
    declared = rng.randrange(5)
    counts = _winning_concealed_hand(rng, declared)
    after_draw = bool(rng.randrange(2))
    if not after_draw:
        tile = rng.choice([tile for tile, count in enumerate(counts) if count])
        counts[tile] -= 1
    # Stay close enough to a hand shape that the exhaustive oracle remains quick.
    for _ in range(rng.randrange(3)):
        _exchange_in_place(rng, counts)
    return tuple(counts), declared


def test_fast_matches_bruteforce_for_320_seeded_hands():
    rng = random.Random(20260717)
    for case in range(320):
        counts, declared = _random_realistic_hand(rng)
        assert shanten(counts, declared) == bruteforce_shanten(counts, declared), (
            case,
            counts,
            declared,
        )
