"""High-volume equivalence checks for the production shanten DP."""

from itertools import product
import random

from taimahjong.bruteforce import bruteforce_shanten
from taimahjong.ev import _production_shanten


def _random_meld(rng):
    if rng.randrange(2):
        tile = rng.randrange(34)
        return (tile, tile, tile)
    tile = rng.randrange(3) * 9 + rng.randrange(7)
    return (tile, tile + 1, tile + 2)


def _random_winning_hand(rng, melds_declared):
    while True:
        counts = [0] * 34
        for _ in range(5 - melds_declared):
            for tile in _random_meld(rng):
                counts[tile] += 1
        counts[rng.randrange(34)] += 2
        if max(counts) <= 4:
            return counts


def test_production_matches_bruteforce_for_50000_seeded_hands():
    """Cover every declared-meld count and both production hand sizes."""
    rng = random.Random(20260806)
    for case in range(50_000):
        melds_declared = case % 5
        counts = _random_winning_hand(rng, melds_declared)
        if case % 2:
            removable = [tile for tile, count in enumerate(counts) if count]
            counts[rng.choice(removable)] -= 1
        hand = tuple(counts)
        assert _production_shanten(hand, melds_declared) == bruteforce_shanten(
            hand, melds_declared
        ), (case, hand, melds_declared)


def test_production_matches_bruteforce_for_all_live_single_suit_shapes():
    """Exhaust all legal one-suit shapes whose tiles still have a live copy.

    Counts stop at three because the legacy shanten definition intentionally
    ignores tile exhaustion, while the exchange oracle cannot draw a fifth
    copy.  Every 16/17-tile legal size for declared meld counts 0..4 is covered.
    """
    declared_by_size = {
        size: melds_declared
        for melds_declared in range(5)
        for size in (16 - 3 * melds_declared, 17 - 3 * melds_declared)
    }
    for suit in product(range(4), repeat=9):
        melds_declared = declared_by_size.get(sum(suit))
        if melds_declared is None:
            continue
        hand = suit + (0,) * 25
        assert _production_shanten(hand, melds_declared) == bruteforce_shanten(
            hand, melds_declared
        ), (hand, melds_declared)
