"""Rule-based opponent-state and deal-in assessment for Taiwanese mahjong.

This module is deliberately deterministic and uncalibrated.  It estimates
which ordinary tenpai shapes could still be possible, rather than claiming a
probability of a deal-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt

from .tiles import validate_counts
from .ukeire import DiscardAnalysis, discard_analysis


# Base shape weights.  All heuristic constants in this module are
# UNCALIBRATED; self-play calibration is a later milestone.
RYANMEN_WEIGHT = 4.0
KANCHAN_WEIGHT = 2.0
PENCHAN_WEIGHT = 2.0
SHANPON_WEIGHT = 2.0
TANKI_WEIGHT = 1.0

# River and hand-reading constants.  They are intentionally simple,
# UNCALIBRATED heuristics.
MIN_RIVER_NUMERIC = 6
LOW_SHARE = 0.15
SUIT_SCARCE = 1.5
SUIT_VOID = 2.0
MELD_FLUSH = 2.0
MELD_FLUSH_HONOR = 1.5
SHAPE_RIVER_DISCOUNT = 0.3

# Opponent-state constants.  These are UNCALIBRATED pseudo-probability inputs.
# Meld count is deliberately the largest tenpai signal: four or five calls
# leave very little concealed hand to complete.  Turn is the number of
# opponent discards observed (or the caller's explicitly supplied turn).  A
# closed hand with an empty river is the dealt hand, whose true tenpai rate is
# zero; later closed-hand probability comes from the turn component.
TENPAI_BASE_BY_MELDS = (0.0, 0.24, 0.43, 0.65, 0.84, 0.94)
TENPAI_TURN_INCREMENT = 0.018
TENPAI_TURN_CAP = 18
TSUMOGIRI_RUN_INCREMENT = 0.08
LATE_TURN = 9
RECENT_TEDASHI_WINDOW = 2
RECENT_TEDASHI_MULTIPLIER = 0.80

# Fold-reading constants.  A folding opponent lowers their win threat and
# raises the chance of a draw (流局), but EV/draw integration is a later
# milestone.
FOLD_WINDOW = 4
MIN_FOLD_SAMPLE = 3
HONOR_FOLD_WEIGHT = 0.6
TERMINAL_FOLD_WEIGHT = 0.3

# The only supported declaration is the Taiwanese house-rule migi.  Its tai
# value is stored for a future scoring milestone and is unused here.
DECLARED_TAI = 8

RIVER_ORIGINS = frozenset(("tsumogiri", "tedashi", "unknown"))


MeldTiles = tuple[int, int, int]
KongTiles = tuple[int, bool]


def _is_tile(tile: object) -> bool:
    return isinstance(tile, int) and not isinstance(tile, bool) and 0 <= tile < 34


def _validate_meld_tiles(tiles: object) -> MeldTiles:
    if not isinstance(tiles, tuple) or len(tiles) != 3 or any(not _is_tile(tile) for tile in tiles):
        raise ValueError("meld tiles must be a tuple of three tile indices 0 through 33")
    return tiles


def _validate_kong_tiles(value: object) -> KongTiles:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError("kong value must be a (tile, concealed) tuple")
    tile, concealed = value
    if not _is_tile(tile):
        raise ValueError("kong tiles must be tile indexes 0-33")
    if not isinstance(concealed, bool):
        raise ValueError("kong concealed flags must be booleans")
    return tile, concealed


@dataclass(frozen=True)
class DeclaredMeld:
    """A called three-tile set with optional source-discard provenance."""

    tiles: MeldTiles
    called_tile: int | None = None
    called_from_seat: int | None = None
    called_from_discard_number: int | None = None

    def __post_init__(self) -> None:
        _validate_meld_tiles(self.tiles)
        call_fields = (
            self.called_tile,
            self.called_from_seat,
            self.called_from_discard_number,
        )
        if all(value is None for value in call_fields):
            return
        if any(value is None for value in call_fields):
            raise ValueError("meld call provenance fields must all be null or all be known")
        if not _is_tile(self.called_tile):
            raise ValueError("called_tile must be an index from 0 through 33")
        if self.called_tile not in self.tiles:
            raise ValueError("called_tile must occur in meld tiles")
        if (
            not isinstance(self.called_from_seat, int)
            or isinstance(self.called_from_seat, bool)
            or self.called_from_seat not in range(4)
        ):
            raise ValueError("called_from_seat must be an absolute seat from 0 through 3")
        if (
            not isinstance(self.called_from_discard_number, int)
            or isinstance(self.called_from_discard_number, bool)
            or self.called_from_discard_number <= 0
        ):
            raise ValueError("called_from_discard_number must be a positive integer")


MeldLike = MeldTiles | DeclaredMeld


def meld_tiles(value: MeldLike) -> MeldTiles:
    """Return the legacy three-tile shape for either supported meld value."""

    return value.tiles if isinstance(value, DeclaredMeld) else _validate_meld_tiles(value)


@dataclass(frozen=True, eq=False)
class DeclaredKong:
    """A declared kong that remains compatible with legacy two-item tuples."""

    tile: int
    concealed: bool
    called_from_seat: int | None = None
    called_from_discard_number: int | None = None

    def __post_init__(self) -> None:
        _validate_kong_tiles((self.tile, self.concealed))
        if self.called_from_seat is None and self.called_from_discard_number is None:
            return
        if self.called_from_seat is None or self.called_from_discard_number is None:
            raise ValueError("kong call provenance fields must both be null or both be known")
        if (
            not isinstance(self.called_from_seat, int)
            or isinstance(self.called_from_seat, bool)
            or self.called_from_seat not in range(4)
        ):
            raise ValueError("called_from_seat must be an absolute seat from 0 through 3")
        if (
            not isinstance(self.called_from_discard_number, int)
            or isinstance(self.called_from_discard_number, bool)
            or self.called_from_discard_number <= 0
        ):
            raise ValueError("called_from_discard_number must be a positive integer")

    def __iter__(self):
        return iter((self.tile, self.concealed))

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index):
        return (self.tile, self.concealed)[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DeclaredKong):
            return (self.tile, self.concealed) == (other.tile, other.concealed)
        return isinstance(other, tuple) and (self.tile, self.concealed) == other

    def __hash__(self) -> int:
        return hash((self.tile, self.concealed))


KongLike = KongTiles | DeclaredKong


def kong_tiles(value: KongLike) -> KongTiles:
    """Return the legacy ``(tile, concealed)`` shape for a declared kong."""

    return (value.tile, value.concealed) if isinstance(value, DeclaredKong) else _validate_kong_tiles(value)


@dataclass(frozen=True)
class RiverEntry:
    """One ordered river tile and its known discard origin."""

    tile: int
    origin: str = "unknown"

    def __post_init__(self) -> None:
        if not _is_tile(self.tile):
            raise ValueError("river tile must be an index from 0 through 33")
        if self.origin not in RIVER_ORIGINS:
            raise ValueError("river origin must be tsumogiri, tedashi, or unknown")


@dataclass
class OpponentView:
    """Public information for the one opponent being modeled.

    ``river`` is ordered oldest to newest and accepts plain tile indices
    (unknown origin) or ``RiverEntry`` values. Every meld is exactly three
    tile indices; this view intentionally does not distinguish call types.
    """

    river: list[int | RiverEntry]
    melds: list[MeldLike]
    declared_at: int | None = None
    # Dealer identity of THIS opponent (seat 0 at the table). The shape
    # heuristics in this module stay seat-blind; these fields exist for the
    # EV layer's loss-magnitude estimate (a streaking dealer's win is worth
    # more, so dealing into them must cost more).
    is_dealer: bool = False
    dealer_streak: int = 0
    # Concealed tile count. Publicly observable in a real game (you can count
    # face-down tiles) even though their identity is hidden, so this is not a
    # leak of concealed information — purely a UI/teaching convenience.
    hand_count: int = 0

    def __post_init__(self) -> None:
        if self.declared_at is not None and (
            not isinstance(self.declared_at, int) or isinstance(self.declared_at, bool) or self.declared_at not in (0, 1)
        ):
            raise ValueError("declared_at must be 0 or 1 for the migi declaration window")
        if not isinstance(self.dealer_streak, int) or isinstance(self.dealer_streak, bool) or self.dealer_streak < 0:
            raise ValueError("dealer_streak must be a non-negative integer")
        if self.dealer_streak and not self.is_dealer:
            raise ValueError("dealer_streak requires is_dealer=True")
        if not isinstance(self.hand_count, int) or isinstance(self.hand_count, bool) or self.hand_count < 0:
            raise ValueError("hand_count must be a non-negative integer")

    def validate(self) -> None:
        """Validate tile indices and public multiplicities in this view."""
        if not isinstance(self.river, list) or any(not _is_river_entry(entry) for entry in self.river):
            raise ValueError("opponent river must be a list of tile indices or RiverEntry values")
        if not isinstance(self.melds, list):
            raise ValueError("opponent melds must be a list of three-tile tuples")
        if self.declared_at is not None:
            if self.declared_at >= len(self.river):
                raise ValueError("declared_at must index a discard in the opponent river")
            if self.melds:
                raise ValueError("a migi declaration cannot follow a called meld")
        public = [0] * 34
        for entry in self.river:
            public[_river_tile(entry)] += 1
        for meld in self.melds:
            for tile in meld_tiles(meld):
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
class TenpaiAssessment:
    """Uncalibrated pseudo-probability and its opponent-state signals."""

    score: float
    signals: dict[str, float | int | bool]
    recent_wait_change: bool


@dataclass(frozen=True)
class DangerDiscardAnalysis:
    """M2 discard analysis with its independent M4a danger assessment."""

    analysis: DiscardAnalysis
    danger: DangerAssessment
    tenpai: TenpaiAssessment
    expected_danger: float

    @property
    def discard(self) -> int:
        return self.analysis.discard

    @property
    def tenpai_score(self) -> float:
        """The shared opponent tenpai score retained alongside raw danger."""
        return self.tenpai.score


def _is_river_entry(entry: object) -> bool:
    return _is_tile(entry) or isinstance(entry, RiverEntry)


def _river_tile(entry: int | RiverEntry) -> int:
    return entry if isinstance(entry, int) else entry.tile


def _river_origin(entry: int | RiverEntry) -> str:
    return "unknown" if isinstance(entry, int) else entry.origin


def _river_tiles(river: list[int | RiverEntry]) -> list[int]:
    return [_river_tile(entry) for entry in river]


def parse_river(text: str) -> list[RiverEntry]:
    """Parse ordered river notation, including ``*`` tsumogiri and ``.`` tedashi.

    A suit suffix applies to every preceding digit/origin pair, so
    ``1*2.3m`` means tsumogiri 1m, tedashi 2m, then an unknown-origin 3m.
    """
    if not isinstance(text, str) or not text:
        raise ValueError("river notation must be a non-empty string")
    result: list[RiverEntry] = []
    pending: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isdigit():
            origin = "unknown"
            if index + 1 < len(text) and text[index + 1] in "*.":
                origin = "tsumogiri" if text[index + 1] == "*" else "tedashi"
                index += 1
            pending.append((char, origin))
        elif char in "mpsz" and pending:
            limit = 7 if char == "z" else 9
            offset = {"m": 0, "p": 9, "s": 18, "z": 27}[char]
            for digit, origin in pending:
                value = int(digit)
                if not 1 <= value <= limit:
                    raise ValueError(f"{digit}{char} is not a valid tile")
                result.append(RiverEntry(offset + value - 1, origin))
            pending = []
        else:
            raise ValueError("expected river digits (optionally * or .) followed by m, p, s, or z")
        index += 1
    if pending:
        raise ValueError("river notation cannot end without a suit")
    return result


def format_river(river: list[int | RiverEntry]) -> str:
    """Format a river while preserving order and compacting adjacent suits."""
    if not isinstance(river, list) or any(not _is_river_entry(entry) for entry in river):
        raise ValueError("river must be a list of tile indices or RiverEntry values")
    pieces: list[str] = []
    pending = ""
    pending_suit: int | None = None
    for entry in river:
        tile = _river_tile(entry)
        suit = tile // 9
        token = str(tile % 9 + 1) + {"tsumogiri": "*", "tedashi": ".", "unknown": ""}[_river_origin(entry)]
        if pending_suit is not None and suit != pending_suit:
            pieces.append(pending + "mpsz"[pending_suit])
            pending = ""
        pending += token
        pending_suit = suit
    if pending_suit is not None:
        pieces.append(pending + "mpsz"[pending_suit])
    return "".join(pieces)


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


# One opponent hand, used as the draw size when turning the unseen pool into
# a per-tile holding chance.
_HAND_TILES = 16


def deal_in_weight(tile: int, belief: tuple[int, ...], pool: int) -> float:
    """Weighted chance one unseen hand is waiting on ``tile``.

    Asking whether any copy of a tile is still unseen makes every tile with one
    copy left look alike.  This asks how a hand could be *waiting* on the tile
    instead: it walks the standard wait shapes above and weights each by the
    chance an opponent holds the tiles that shape needs.

    Two approximations, both forced by what a seat may look at.  The seat knows
    only its own hand and the unseen pool, so an opponent's hand is treated as
    a draw from that pool, and each required tile is treated as drawn
    independently -- true only in the limit of a large pool.  What this keeps is
    the ordering *between* live tiles: a tile whose neighbours are gone is safer
    than one whose neighbours are live, even when both still have copies unseen.

    It lives here, rather than beside the empirical game that first used it,
    because every module needing a seat-information danger estimate sits above
    this one: a policy in :mod:`taimahjong.ev` cannot import the empirical game.
    """
    if pool <= 0:
        return 0.0
    total = 0.0
    for _, required, weight in _wait_shapes(tile):
        chance = 1.0
        for needed in required:
            # An opponent holds 16 of the ``pool`` unseen tiles.
            chance *= min(1.0, _HAND_TILES * belief[needed] / pool)
        total += weight * chance
    return total


def _recent_river_indexes(river: list[int | RiverEntry]) -> set[int]:
    """Return the newest third of a nonempty river, rounded up."""
    if not river:
        return set()
    recent = ceil(len(river) / 3)
    return set(range(len(river) - recent, len(river)))


def _shape_river_multiplier(required_tiles: tuple[int, ...], river: list[int | RiverEntry]) -> float:
    """Discount once per distinct required kind found in the river."""
    recent = _recent_river_indexes(river)
    multiplier = 1.0
    for required in set(required_tiles):
        indexes = [index for index, entry in enumerate(river) if _river_tile(entry) == required]
        if not indexes:
            continue
        multiplier *= SHAPE_RIVER_DISCOUNT if any(index in recent for index in indexes) else sqrt(SHAPE_RIVER_DISCOUNT)
    return multiplier


def _suit_void_multiplier(tile: int, river: list[int | RiverEntry]) -> tuple[str | None, float]:
    """Infer a likely kept suit from plain numeric-suit river counts."""
    suit = _numeric_suit(tile)
    numeric = [river_tile for river_tile in _river_tiles(river) if _numeric_suit(river_tile) is not None]
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
    suits = {_numeric_suit(tile) for meld in opponent.melds for tile in meld_tiles(meld)}
    if len(suits) != 1 or None in suits:
        return None
    return suits.pop()


def _flush_multiplier(tile: int, opponent: OpponentView) -> tuple[str | None, float]:
    """Apply a simple flush read when the newest third avoids its meld suit."""
    suit = _flush_suit(opponent)
    recent_indexes = _recent_river_indexes(opponent.river)
    if suit is None or not recent_indexes or any(
        _numeric_suit(_river_tile(opponent.river[index])) == suit for index in recent_indexes
    ):
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
    for river_entry in opponent.river:
        opponent_public[_river_tile(river_entry)] += 1
    for meld in opponent.melds:
        for meld_tile in meld_tiles(meld):
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
    return assess_validated_danger(tile, opponent, seen, hand)


def assess_validated_danger(
    tile: int,
    opponent: OpponentView,
    seen: tuple[int, ...],
    hand: tuple[int, ...],
) -> DangerAssessment:
    """:func:`danger_score` without the argument checks, for rollout hot paths.

    Terminal rollouts call this once per live opponent per discard — hundreds of
    thousands of times for a single quiz question — and build both count vectors
    themselves from state that is already well formed.  Re-validating there costs
    more than the assessment it guards.  Callers taking counts from outside the
    engine must go through :func:`danger_score` instead.
    """
    if opponent.declared_at is not None and any(
        _river_tile(entry) == tile for entry in opponent.river[opponent.declared_at + 1 :]
    ):
        return DangerAssessment(0.0, [], {"declared_safe": 1.0})
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


def _trailing_tsumogiri_run(river: list[int | RiverEntry]) -> int:
    """Count trailing known tsumogiri, skipping unknown origins.

    Scan newest to oldest.  Unknown entries are neutral: they neither extend
    the run nor reset it.  The first known tedashi ends the run, while known
    tsumogiri entries before it count toward the run.
    """
    run = 0
    for entry in reversed(river):
        origin = _river_origin(entry)
        if origin == "unknown":
            continue
        if origin == "tedashi":
            break
        run += 1
    return run


def tenpai_score(opponent: OpponentView, turn: int) -> TenpaiAssessment:
    """Estimate one opponent's tenpai state with UNCALIBRATED heuristics."""
    opponent.validate()
    if not isinstance(turn, int) or isinstance(turn, bool) or turn < 0:
        raise ValueError("turn must be a non-negative integer")
    if opponent.declared_at is not None:
        return TenpaiAssessment(1.0, {"declared": True}, False)

    meld_count = len(opponent.melds)
    meld_base = TENPAI_BASE_BY_MELDS[min(meld_count, len(TENPAI_BASE_BY_MELDS) - 1)]
    turn_component = min(turn, TENPAI_TURN_CAP) * TENPAI_TURN_INCREMENT
    run = _trailing_tsumogiri_run(opponent.river)
    tsumogiri_multiplier = 1.0 + run * TSUMOGIRI_RUN_INCREMENT
    recent_tedashi = turn >= LATE_TURN and any(
        _river_origin(entry) == "tedashi" for entry in opponent.river[-RECENT_TEDASHI_WINDOW:]
    )
    wait_change_multiplier = RECENT_TEDASHI_MULTIPLIER if recent_tedashi else 1.0
    score = min(1.0, max(0.0, (meld_base + turn_component) * tsumogiri_multiplier * wait_change_multiplier))
    signals: dict[str, float | int | bool] = {
        "meld_base": meld_base,
        "turn_component": turn_component,
        "trailing_tsumogiri_run": run,
        "tsumogiri_multiplier": tsumogiri_multiplier,
    }
    if recent_tedashi:
        signals["recent_tedashi_multiplier"] = wait_change_multiplier
    return TenpaiAssessment(score, signals, recent_tedashi)


def _other_discard_counts(others_discards: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Accept either a 34-count vector or an ordered list of tile kinds."""
    if not isinstance(others_discards, (tuple, list)):
        raise ValueError("others_discards must be a list of tile kinds or 34 tile counts")
    if len(others_discards) == 34:
        return validate_counts(others_discards)
    if any(not _is_tile(tile) for tile in others_discards):
        raise ValueError("others_discards must contain tile indices 0 through 33")
    counts = [0] * 34
    for tile in others_discards:
        counts[tile] += 1
    return tuple(counts)


def _is_terminal(tile: int) -> bool:
    return tile < 27 and tile % 9 in (0, 8)


def fold_score(opponent: OpponentView, others_discards: tuple[int, ...] | list[int]) -> float:
    """Estimate folding from the newest safety-shaped river discards.

    A recent tedashi middle tile (3--7) gets zero weight because choosing it
    from hand conflicts with a pure defensive fold.  Other safety signals use
    the strongest applicable weight: another player's matching discard (1),
    honor (0.6), then terminal (0.3).
    """
    opponent.validate()
    if opponent.declared_at is not None:
        return 0.0
    reference = _other_discard_counts(others_discards)
    window = opponent.river[-FOLD_WINDOW:]
    if len(window) < MIN_FOLD_SAMPLE:
        return 0.0
    total = 0.0
    for entry in window:
        tile = _river_tile(entry)
        if _river_origin(entry) == "tedashi" and tile < 27 and 2 <= tile % 9 <= 6:
            weight = 0.0
        elif reference[tile]:
            weight = 1.0
        elif tile >= 27:
            weight = HONOR_FOLD_WEIGHT
        elif _is_terminal(tile):
            weight = TERMINAL_FOLD_WEIGHT
        else:
            weight = 0.0
        total += weight
    return min(1.0, max(0.0, total / len(window)))


def rank_discards(
    counts17: tuple[int, ...] | list[int],
    opponent: OpponentView,
    visible: tuple[int, ...] | list[int],
    melds_declared: int = 0,
    turn: int | None = None,
) -> list[DangerDiscardAnalysis]:
    """Attach M4a+ danger and tenpai state to M2-ranked discards.

    ``turn`` defaults to the number of observed opponent discards.  Raw danger
    and tenpai remain independent; ``expected_danger`` is only their
    convenience product.
    """
    analyses = discard_analysis(counts17, melds_declared, visible)
    opponent_tenpai = tenpai_score(opponent, len(opponent.river) if turn is None else turn)
    results: list[DangerDiscardAnalysis] = []
    for analysis in analyses:
        post_discard = list(counts17)
        post_discard[analysis.discard] -= 1
        danger = danger_score(analysis.discard, opponent, visible, post_discard)
        results.append(DangerDiscardAnalysis(analysis, danger, opponent_tenpai, danger.score * opponent_tenpai.score))
    return results
