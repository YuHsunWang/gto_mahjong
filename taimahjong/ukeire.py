"""Tile-acceptance and discard analysis for Taiwanese mahjong hands."""

from __future__ import annotations

from dataclasses import dataclass

from .shanten import shanten
from .tiles import validate_counts


@dataclass(frozen=True)
class DiscardAnalysis:
    """The shanten and acceptance result after discarding one tile kind."""

    discard: int
    shanten_after: int
    ukeire: dict[int, int]
    total: int


def _validate_hand_size(
    counts: tuple[int, ...] | list[int], melds_declared: int, expected_size: int
) -> tuple[tuple[int, ...], int]:
    """Validate a M1 hand and require one exact concealed hand size."""
    checked = validate_counts(counts)
    current_shanten = shanten(checked, melds_declared)
    if sum(checked) != expected_size:
        raise ValueError(
            f"concealed hand has {sum(checked)} tiles; expected {expected_size} for {melds_declared} declared meld(s)"
        )
    return checked, current_shanten


def _validate_visible(visible: tuple[int, ...] | list[int] | None, hand: tuple[int, ...]) -> tuple[int, ...]:
    """Validate visible tiles and ensure no tile kind has more than four copies."""
    checked = (0,) * 34 if visible is None else validate_counts(visible)
    if any(hand[tile] + checked[tile] > 4 for tile in range(34)):
        raise ValueError("hand and visible tiles cannot contain more than four copies of a tile kind")
    return checked


def ukeire(
    counts: tuple[int, ...] | list[int], melds_declared: int = 0, visible: tuple[int, ...] | list[int] | None = None
) -> dict[int, int]:
    """Return shanten-improving draws and their remaining unseen copies.

    Tile kinds with zero unseen copies remain in the result when that draw
    would improve shanten; this preserves the complete theoretical acceptance
    set while showing that the tile is unavailable.
    """
    expected_size = 16 - 3 * melds_declared if isinstance(melds_declared, int) and not isinstance(melds_declared, bool) else 16
    hand, current_shanten = _validate_hand_size(counts, melds_declared, expected_size)
    seen = _validate_visible(visible, hand)

    accepted: dict[int, int] = {}
    for tile, count in enumerate(hand):
        if count == 4:
            continue
        drawn = list(hand)
        drawn[tile] += 1
        if shanten(tuple(drawn), melds_declared) < current_shanten:
            accepted[tile] = 4 - hand[tile] - seen[tile]
    return accepted


def discard_analysis(
    counts: tuple[int, ...] | list[int], melds_declared: int = 0, visible: tuple[int, ...] | list[int] | None = None
) -> list[DiscardAnalysis]:
    """Rank distinct discards from a post-draw hand by shanten and ukeire."""
    expected_size = 17 - 3 * melds_declared if isinstance(melds_declared, int) and not isinstance(melds_declared, bool) else 17
    hand, _ = _validate_hand_size(counts, melds_declared, expected_size)
    seen = _validate_visible(visible, hand)

    analyses: list[DiscardAnalysis] = []
    for tile, count in enumerate(hand):
        if not count:
            continue
        post_discard = list(hand)
        post_discard[tile] -= 1
        after = tuple(post_discard)
        attack_visible = list(seen)
        attack_visible[tile] += 1
        accepted = ukeire(after, melds_declared, attack_visible)
        analyses.append(
            DiscardAnalysis(
                discard=tile,
                shanten_after=shanten(after, melds_declared),
                ukeire=accepted,
                total=sum(accepted.values()),
            )
        )
    return sorted(analyses, key=lambda analysis: (analysis.shanten_after, -analysis.total, analysis.discard))
