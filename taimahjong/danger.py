"""Rule-based deal-in danger assessment for one Taiwanese-mahjong opponent.

This module is deliberately deterministic and uncalibrated.  It estimates
which ordinary tenpai shapes could still be possible, rather than claiming a
probability of a deal-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt

from .tiles import validate_counts
from .ukeire import DiscardAnalysis, discard_analysis


# Base shape weights.  M4b calibration may change these without changing the
# feasibility or evidence rules below.
RYANMEN_WEIGHT = 4.0
KANCHAN_WEIGHT = 2.0
PENCHAN_WEIGHT = 2.0
SHANPON_WEIGHT = 2.0
TANKI_WEIGHT = 1.0

# River and hand-reading constants.  They are intentionally simple heuristics.
MIN_RIVER_NUMERIC = 6
LOW_SHARE = 0.15
SUIT_SCARCE = 1.5
SUIT_VOID = 2.0
MELD_FLUSH = 2.0
MELD_FLUSH_HONOR = 1.5
SHAPE_RIVER_DISCOUNT = 0.3


@dataclass
class OpponentView:
    """Public information for the one opponent being modeled.

    ``river`` is ordered oldest to newest.  Every meld is exactly three tile
    indices; this M4a view intentionally does not distinguish calls.
    """

    river: list[int]
    melds: list[tuple[int, int, int]]

    def validate(self) -> None:
        """Validate tile indices and public multiplicities in this view."""
        if not isinstance(self.river, list) or any(not _is_tile(tile) for tile in self.river):
            raise ValueError("opponent river must be a list of tile indices 0 through 33")
        if not isinstance(self.melds, list):
            raise ValueError("opponent melds must be a list of three-tile tuples")
        public = [0] * 34
        for tile in self.river:
            public[tile] += 1
        for meld in self.melds:
            if not isinstance(meld, tuple) or len(meld) != 3 or any(not _is_tile(tile) for tile in meld):
                raise ValueError("each opponent meld must be a tuple of three tile indices 0 through 33")
            for tile in meld:
                public[tile] += 1
        if any(count > 4 for count in public):
            raise ValueError("opponent river and melds cannot contain more than four copies of a tile kind")


@dataclass(frozen=True)
class WaitShape:
    """One feasible way the opponent could hold tiles while waiting on a discard."""

    name: str
    required_tiles: tuple[int, ...]
    base_weight: float
    river_multiplier: float
    weight: float


@dataclass(frozen=True)
class DangerAssessment:
    """Uncalibrated danger result for one candidate discard."""

    score: float
    feasible_shapes: list[WaitShape]
    modifiers: dict[str, float]


@dataclass(frozen=True)
class DangerDiscardAnalysis:
    """M2 discard analysis with its independent M4a danger assessment."""

    analysis: DiscardAnalysis
    danger: DangerAssessment

    @property
    def discard(self) -> int:
        return self.analysis.discard


def _is_tile(tile: object) -> bool:
    return isinstance(tile, int) and not isinstance(tile, bool) and 0 <= tile < 34


def _numeric_suit(tile: int) -> int | None:
    return tile // 9 if tile < 27 else None


def _wait_shapes(tile: int) -> list[tuple[str, tuple[int, ...], float]]:
    """Return all standard shapes whose final tile can be ``tile``.

    A side shape is ``penchan`` only when its two held tiles make an actual
    edge wait (12 waiting 3, or 89 waiting 7).  Thus 23 waiting 1 is a
    ryanmen shape, as it can also accept 4.
    """
    shapes: list[tuple[str, tuple[int, ...], float]] = [
        ("tanki", (tile,), TANKI_WEIGHT),
        ("shanpon", (tile,), SHANPON_WEIGHT),
    ]
    suit = _numeric_suit(tile)
    if suit is None:
        return shapes
    offset = suit * 9
    rank = tile - offset + 1
    if rank <= 7:
        name = "penchan" if rank == 7 else "ryanmen"
        shapes.append((name, (tile + 1, tile + 2), PENCHAN_WEIGHT if name == "penchan" else RYANMEN_WEIGHT))
    if rank >= 3:
        name = "penchan" if rank == 3 else "ryanmen"
        shapes.append((name, (tile - 2, tile - 1), PENCHAN_WEIGHT if name == "penchan" else RYANMEN_WEIGHT))
    if 2 <= rank <= 8:
        shapes.append(("kanchan", (tile - 1, tile + 1), KANCHAN_WEIGHT))
    return shapes


def _recent_river_indexes(river: list[int]) -> set[int]:
    """Return the newest third of a nonempty river, rounded up."""
    if not river:
        return set()
    recent = ceil(len(river) / 3)
    return set(range(len(river) - recent, len(river)))


def _shape_river_multiplier(required_tiles: tuple[int, ...], river: list[int]) -> float:
    """Discount once per distinct required kind found in the river."""
    recent = _recent_river_indexes(river)
    multiplier = 1.0
    for required in set(required_tiles):
        indexes = [index for index, tile in enumerate(river) if tile == required]
        if not indexes:
            continue
        multiplier *= SHAPE_RIVER_DISCOUNT if any(index in recent for index in indexes) else sqrt(SHAPE_RIVER_DISCOUNT)
    return multiplier


def _suit_void_multiplier(tile: int, river: list[int]) -> tuple[str | None, float]:
    """Infer a likely kept suit from plain numeric-suit river counts."""
    suit = _numeric_suit(tile)
    numeric = [river_tile for river_tile in river if _numeric_suit(river_tile) is not None]
    if suit is None or len(numeric) < MIN_RIVER_NUMERIC:
        return None, 1.0
    count = sum(_numeric_suit(river_tile) == suit for river_tile in numeric)
    if count == 0:
        return "suit_void", SUIT_VOID
    if count / len(numeric) < LOW_SHARE:
        return "suit_scarce", SUIT_SCARCE
    return None, 1.0


def _flush_suit(opponent: OpponentView) -> int | None:
    """Return the committed suit when all declared melds are in one suit."""
    if not opponent.melds:
        return None
    suits = {_numeric_suit(tile) for meld in opponent.melds for tile in meld}
    if len(suits) != 1 or None in suits:
        return None
    return suits.pop()


def _flush_multiplier(tile: int, opponent: OpponentView) -> tuple[str | None, float]:
    """Apply a simple flush read when the newest third avoids its meld suit."""
    suit = _flush_suit(opponent)
    recent_indexes = _recent_river_indexes(opponent.river)
    if suit is None or not recent_indexes or any(_numeric_suit(opponent.river[index]) == suit for index in recent_indexes):
        return None, 1.0
    tile_suit = _numeric_suit(tile)
    if tile_suit == suit:
        return "meld_flush", MELD_FLUSH
    if tile_suit is None:
        return "meld_flush_honor", MELD_FLUSH_HONOR
    return None, 1.0


def _validate_inputs(
    tile: int, opponent: OpponentView, visible: tuple[int, ...] | list[int], own_hand: tuple[int, ...] | list[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if not _is_tile(tile):
        raise ValueError("discard tile must be an index from 0 through 33")
    opponent.validate()
    seen = validate_counts(visible)
    hand = validate_counts(own_hand)
    opponent_public = [0] * 34
    for river_tile in opponent.river:
        opponent_public[river_tile] += 1
    for meld in opponent.melds:
        for meld_tile in meld:
            opponent_public[meld_tile] += 1
    if any(seen[index] < opponent_public[index] for index in range(34)):
        raise ValueError("visible must include the opponent river and melds")
    if any(seen[index] + hand[index] + (1 if index == tile else 0) > 4 for index in range(34)):
        raise ValueError("visible tiles, remaining own hand, and discarded tile cannot contain more than four copies")
    return seen, hand


def danger_score(
    tile: int, opponent: OpponentView, visible: tuple[int, ...] | list[int], own_hand: tuple[int, ...] | list[int]
) -> DangerAssessment:
    """Assess one discard against one opponent's publicly modeled hand read.

    ``own_hand`` is the *post-discard* concealed hand: it excludes the one
    copy of ``tile`` being discarded.  ``visible`` includes every public tile
    known to the caller, including ``opponent.river`` and ``opponent.melds``,
    but excludes ``own_hand`` and this discard.  Thus the unseen count is
    ``4 - visible[tile] - own_hand[tile] - (tile is the discard)``.

    River evidence is only statistical.  Taiwanese mahjong has no permanent
    Japanese-riichi furiten: a river tile discounts a shape but never removes
    it from feasibility.
    """
    seen, hand = _validate_inputs(tile, opponent, visible, own_hand)
    unseen = [4 - seen[index] - hand[index] - (1 if index == tile else 0) for index in range(34)]
    feasible: list[WaitShape] = []
    for name, required, base_weight in _wait_shapes(tile):
        need = 2 if name == "shanpon" else 1
        if len(required) == 1:
            is_feasible = unseen[required[0]] >= need
        else:
            is_feasible = all(unseen[required_tile] >= 1 for required_tile in required)
        if is_feasible:
            river_multiplier = _shape_river_multiplier(required, opponent.river)
            feasible.append(WaitShape(name, required, base_weight, river_multiplier, base_weight * river_multiplier))

    suit_name, suit_multiplier = _suit_void_multiplier(tile, opponent.river)
    flush_name, flush_multiplier = _flush_multiplier(tile, opponent)
    modifiers: dict[str, float] = {}
    if suit_name:
        modifiers[suit_name] = suit_multiplier
    if flush_name:
        modifiers[flush_name] = flush_multiplier
    # A shared suit inference and flush commitment express the same broad
    # signal, so use their maximum rather than multiplying the confidence.
    global_multiplier = max(suit_multiplier, flush_multiplier)
    if suit_name and flush_name:
        modifiers["suit_flush_max"] = global_multiplier
    score = sum(shape.weight for shape in feasible) * global_multiplier
    return DangerAssessment(score, feasible, modifiers)


def rank_discards(
    counts17: tuple[int, ...] | list[int], opponent: OpponentView, visible: tuple[int, ...] | list[int], melds_declared: int = 0
) -> list[DangerDiscardAnalysis]:
    """Attach M4a danger to M2-ranked discards without combining their scores."""
    analyses = discard_analysis(counts17, melds_declared, visible)
    results: list[DangerDiscardAnalysis] = []
    for analysis in analyses:
        post_discard = list(counts17)
        post_discard[analysis.discard] -= 1
        results.append(DangerDiscardAnalysis(analysis, danger_score(analysis.discard, opponent, visible, post_discard)))
    return results
