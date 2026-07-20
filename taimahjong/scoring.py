"""Deterministic tai (台) scoring for completed Taiwanese 16-tile hands.

House rules encoded (2026-07-17):
- Money ratio: one base (底) equals ``BASE_UNITS`` tai (e.g. 300/100).
- Standard Taiwanese tai table; every value is a module constant so a
  different house table only needs constant edits.
- Flowers and kongs are not modelled by the engine; ``WinContext.extra``
  is the reserved slot for such externally-supplied tai items.
- The migi declaration bonus reuses ``danger.DECLARED_TAI``.
- Heavenly/earthly hands use the confirmed house values (16/8 tai).

Documented stacking choices (adjust constants if the house disagrees):
- Individual dragon triplet tai does not stack with 小三元/大三元; round/seat
  wind tai does not stack with 小四喜/大四喜.
- 字一色 stacks with 碰碰胡 and concealed-triplet tai.
- 平胡 requires all runs, a non-honor pair and a multi-kind wait; it may
  stack with self-draw.
- Only the highest concealed-triplet tier (三/四/五暗刻) is counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .danger import DECLARED_TAI
from .shanten import shanten
from .tiles import validate_counts

BASE_UNITS = 3  # one 底 is worth this many 台 (house: 300 base / 100 per tai)

DEALER_TAI = 1
STREAK_TAI_PER_WIN = 2  # 連N拉N: 2 tai per consecutive dealer repeat
MENQING_TAI = 1
SELF_DRAW_TAI = 1
SINGLE_WAIT_TAI = 1
PINGHU_TAI = 2
ALL_CALLED_TAI = 2
THREE_CONCEALED_TAI = 2
FOUR_CONCEALED_TAI = 5
FIVE_CONCEALED_TAI = 8
ALL_TRIPLETS_TAI = 4
HALF_FLUSH_TAI = 4
FULL_FLUSH_TAI = 8
ALL_HONORS_TAI = 16
DRAGON_TRIPLET_TAI = 1
SMALL_DRAGONS_TAI = 4
BIG_DRAGONS_TAI = 8
ROUND_WIND_TAI = 1
SEAT_WIND_TAI = 1
SMALL_WINDS_TAI = 8
BIG_WINDS_TAI = 16
HEAVENLY_TAI = 16
EARTHLY_TAI = 8
MIGI_TAI = DECLARED_TAI
# House rule (2026-07-18): open and concealed kongs score no tai on their own;
# only winning on the replacement tile (槓上開花) and robbing a kong (搶槓) do.
OPEN_KONG_TAI = 0
CONCEALED_KONG_TAI = 0
KONG_BLOOM_TAI = 1
ROBBED_KONG_TAI = 1

WIND_TILES = frozenset(range(27, 31))
DRAGON_TILES = frozenset(range(31, 34))


@dataclass(frozen=True)
class ScoringScheme:
    """House 底/台 payout convention: a win is worth ``base_units`` plus
    ``tai_units`` per 台.

    Changing the 底:台 ratio shifts the value of a flat win relative to a big
    hand (a larger 底 rewards just-winning; a larger 台 rewards building), so a
    scheme can change EV-optimal play — the reason the trainer lets you pick
    one. It is a payout convention, orthogonal to a hand's tai, so it is passed
    alongside :class:`WinContext` rather than stored in it.
    """

    base_units: int
    tai_units: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.base_units, int) or isinstance(self.base_units, bool) or self.base_units < 0:
            raise ValueError("base_units must be a non-negative integer")
        if not isinstance(self.tai_units, int) or isinstance(self.tai_units, bool) or self.tai_units < 1:
            raise ValueError("tai_units must be a positive integer")

    def value(self, total_tai: int) -> int:
        """Win value in chip units: 底 + 每台 × 台數."""
        return self.base_units + self.tai_units * total_tai


# 底3台1 is the house default and equals the BASE_UNITS model (value_units).
# Self-play, calibration, and the CLI all keep this scheme; only the teaching
# EV path lets the user swap in another.
SCHEME_3_1 = ScoringScheme(BASE_UNITS, 1)
SCHEME_5_2 = ScoringScheme(5, 2)
DEFAULT_SCHEME = SCHEME_3_1


@dataclass(frozen=True)
class WinContext:
    """Everything about the win that is not visible in the tiles."""

    winning_tile: int
    self_draw: bool = False
    dealer: bool = False
    dealer_streak: int = 0
    migi_declared: bool = False
    heavenly: bool = False
    earthly: bool = False
    round_wind: int | None = None
    seat_wind: int | None = None
    # 槓上開花: self-draw on a kong's replacement tile. House rule — only a kong
    # whose fourth tile was self-drawn (暗槓 / 加槓) qualifies; a 大明槓 (fourth
    # tile called off a discard) does not. The engine enforces this and only
    # sets the flag when eligible; scoring just honours it.
    kong_bloom: bool = False
    robbed_kong: bool = False  # 搶槓: ron on an opponent's added-kong tile
    extra: tuple[tuple[str, int], ...] = ()  # reserved: flowers, ...

    def __post_init__(self) -> None:
        if not 0 <= self.winning_tile < 34:
            raise ValueError("winning_tile must be a tile index 0-33")
        if self.dealer_streak < 0:
            raise ValueError("dealer_streak must be >= 0")
        if self.dealer_streak and not self.dealer:
            raise ValueError("dealer_streak requires dealer=True")
        if self.heavenly and self.earthly:
            raise ValueError("a win cannot be both heavenly and earthly")
        if self.kong_bloom and not self.self_draw:
            raise ValueError("kong_bloom (槓上開花) is a self-draw win")
        if self.robbed_kong and self.self_draw:
            raise ValueError("robbed_kong (搶槓) is a ron win")
        for wind in (self.round_wind, self.seat_wind):
            if wind is not None and wind not in WIND_TILES:
                raise ValueError("winds must be wind tile indexes (1z-4z)")


@dataclass(frozen=True)
class ScoreResult:
    items: tuple[tuple[str, int], ...]
    total_tai: int

    @property
    def value_units(self) -> int:
        """Win value under the house default scheme (底3台1): 底 + 台."""
        return BASE_UNITS + self.total_tai

    def value_in(self, scheme: "ScoringScheme") -> int:
        """Win value under an explicit 底/台 scheme."""
        return scheme.value(self.total_tai)


def _classify_meld(meld: tuple[int, int, int]) -> tuple[str, int]:
    tiles = tuple(sorted(meld))
    if any(not 0 <= tile < 34 for tile in tiles):
        raise ValueError("meld tiles must be tile indexes 0-33")
    if tiles[0] == tiles[1] == tiles[2]:
        return ("tri", tiles[0])
    if (
        tiles[2] < 27
        and tiles[0] // 9 == tiles[2] // 9
        and tiles[1] == tiles[0] + 1
        and tiles[2] == tiles[0] + 2
    ):
        return ("run", tiles[0])
    raise ValueError("each meld must be a triplet or a suited run")


def _decompose_sets(counts: list[int], sets_needed: int, start: int) -> list[list[tuple[str, int]]]:
    while start < 34 and counts[start] == 0:
        start += 1
    if sets_needed == 0:
        return [[]] if start == 34 else []
    if start == 34:
        return []
    results: list[list[tuple[str, int]]] = []
    if counts[start] >= 3:
        counts[start] -= 3
        for rest in _decompose_sets(counts, sets_needed - 1, start):
            results.append([("tri", start)] + rest)
        counts[start] += 3
    if start < 27 and start % 9 <= 6 and counts[start + 1] and counts[start + 2]:
        for tile in (start, start + 1, start + 2):
            counts[tile] -= 1
        for rest in _decompose_sets(counts, sets_needed - 1, start):
            results.append([("run", start)] + rest)
        for tile in (start, start + 1, start + 2):
            counts[tile] += 1
    return results


def _decompositions(concealed: tuple[int, ...], sets_needed: int) -> list[tuple[int, list[tuple[str, int]]]]:
    """All (pair kind, concealed sets) splits of a winning concealed hand."""
    results: list[tuple[int, list[tuple[str, int]]]] = []
    working = list(concealed)
    for pair in range(34):
        if working[pair] < 2:
            continue
        working[pair] -= 2
        for sets in _decompose_sets(working, sets_needed, 0):
            results.append((pair, sets))
        working[pair] += 2
    return results


def _winning_kinds(pre_win: list[int], melds_declared: int) -> list[int]:
    kinds: list[int] = []
    for tile in range(34):
        if pre_win[tile] == 4:
            continue
        pre_win[tile] += 1
        if shanten(tuple(pre_win), melds_declared) == -1:
            kinds.append(tile)
        pre_win[tile] -= 1
    return kinds


def _score_decomposition(
    pair: int,
    concealed_sets: list[tuple[str, int]],
    meld_sets: list[tuple[str, int]],
    context: WinContext,
    single_wait: bool,
    suits_present: set[int],
    honors_present: bool,
    kong_sets: list[tuple[str, int]] = (),
    concealed_kong_count: int = 0,
    open_kong_count: int = 0,
) -> ScoreResult:
    items: list[tuple[str, int]] = []
    win = context.winning_tile
    # Kongs score like triplets for every pattern; concealed kongs also count
    # toward concealed-triplet tai (三/四/五暗刻).
    all_sets = concealed_sets + meld_sets + list(kong_sets)

    concealed_triplets = sum(1 for kind, tile in concealed_sets if kind == "tri")
    if not context.self_draw and concealed_triplets:
        in_run = any(
            kind == "run" and tile <= win <= tile + 2 and tile // 9 == win // 9
            for kind, tile in concealed_sets
        )
        in_triplet = any(kind == "tri" and tile == win for kind, tile in concealed_sets)
        if in_triplet and not in_run and pair != win:
            concealed_triplets -= 1  # the ron tile completed this triplet openly
    concealed_triplets += concealed_kong_count

    if context.heavenly:
        items.append(("heavenly (天胡)", HEAVENLY_TAI))
    if context.earthly:
        items.append(("earthly (地胡)", EARTHLY_TAI))
    if context.migi_declared:
        items.append(("migi declaration (宣告聽牌)", MIGI_TAI))
    # These dealer items apply to a DEALER WINNER only. When a non-dealer wins,
    # the bilateral premium on the dealer's payment leg is added by the caller's
    # settlement (selfplay._dealer_leg_premium) — never both.
    if context.dealer:
        items.append(("dealer (莊家)", DEALER_TAI))
    if context.dealer_streak:
        items.append((f"dealer streak x{context.dealer_streak} (連莊拉莊)", STREAK_TAI_PER_WIN * context.dealer_streak))
    if not meld_sets and not open_kong_count:
        # Concealed kongs keep the hand 門清; only open calls break it.
        items.append(("concealed hand (門清)", MENQING_TAI))
    if context.self_draw:
        items.append(("self-draw (自摸)", SELF_DRAW_TAI))
    if context.kong_bloom:
        items.append(("kong bloom (槓上開花)", KONG_BLOOM_TAI))
    if context.robbed_kong:
        items.append(("robbing the kong (搶槓)", ROBBED_KONG_TAI))
    if single_wait:
        items.append(("single wait (獨聽)", SINGLE_WAIT_TAI))
    if len(meld_sets) == 5 and not context.self_draw:
        items.append(("all called (全求人)", ALL_CALLED_TAI))

    if all(kind == "run" for kind, _ in all_sets) and pair < 27 and not single_wait:
        items.append(("all runs (平胡)", PINGHU_TAI))
    if all(kind == "tri" for kind, _ in all_sets):
        items.append(("all triplets (碰碰胡)", ALL_TRIPLETS_TAI))

    if concealed_triplets >= 5:
        items.append(("five concealed triplets (五暗刻)", FIVE_CONCEALED_TAI))
    elif concealed_triplets == 4:
        items.append(("four concealed triplets (四暗刻)", FOUR_CONCEALED_TAI))
    elif concealed_triplets == 3:
        items.append(("three concealed triplets (三暗刻)", THREE_CONCEALED_TAI))

    if not suits_present and honors_present:
        items.append(("all honors (字一色)", ALL_HONORS_TAI))
    elif len(suits_present) == 1:
        if honors_present:
            items.append(("half flush (混一色)", HALF_FLUSH_TAI))
        else:
            items.append(("full flush (清一色)", FULL_FLUSH_TAI))

    dragon_triplets = sum(1 for kind, tile in all_sets if kind == "tri" and tile in DRAGON_TILES)
    if dragon_triplets == 3:
        items.append(("big three dragons (大三元)", BIG_DRAGONS_TAI))
    elif dragon_triplets == 2 and pair in DRAGON_TILES:
        items.append(("small three dragons (小三元)", SMALL_DRAGONS_TAI))
    elif dragon_triplets:
        items.append((f"dragon triplets x{dragon_triplets} (三元牌刻)", DRAGON_TRIPLET_TAI * dragon_triplets))

    wind_triplets = sum(1 for kind, tile in all_sets if kind == "tri" and tile in WIND_TILES)
    wind_kinds = {tile for kind, tile in all_sets if kind == "tri" and tile in WIND_TILES}
    if wind_triplets == 4:
        items.append(("big four winds (大四喜)", BIG_WINDS_TAI))
    elif wind_triplets == 3 and pair in WIND_TILES:
        items.append(("small four winds (小四喜)", SMALL_WINDS_TAI))
    else:
        if context.round_wind in wind_kinds:
            items.append(("round wind (圈風)", ROUND_WIND_TAI))
        if context.seat_wind in wind_kinds:
            items.append(("seat wind (門風)", SEAT_WIND_TAI))

    items.extend(context.extra)
    return ScoreResult(tuple(items), sum(tai for _, tai in items))


def score_hand(
    concealed: tuple[int, ...] | list[int],
    melds: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...] = (),
    context: WinContext | None = None,
    kongs: tuple[tuple[int, bool], ...] = (),
) -> ScoreResult:
    """Score a complete winning hand: concealed tiles include the winning tile.

    ``kongs`` lists declared kongs as ``(tile, concealed)`` pairs; each counts
    as one completed set (like a triplet) and its four tiles live outside
    ``concealed``. A concealed kong (暗槓) also counts toward concealed-triplet
    tai; an open kong does not, and it breaks 門清.
    """
    if context is None:
        raise ValueError("a WinContext with the winning tile is required")
    checked = validate_counts(concealed)
    meld_sets = [_classify_meld(tuple(meld)) for meld in melds]
    for tile, _ in kongs:
        if not 0 <= tile < 34:
            raise ValueError("kong tiles must be tile indexes 0-33")
    declared_sets = len(meld_sets) + len(kongs)
    if declared_sets > 5:
        raise ValueError("at most five sets can be declared")
    kong_sets = [("tri", tile) for tile, _ in kongs]
    concealed_kong_count = sum(1 for _, concealed_flag in kongs if concealed_flag)
    open_kong_count = len(kongs) - concealed_kong_count

    expected = 17 - 3 * declared_sets
    if sum(checked) != expected:
        raise ValueError(f"concealed hand has {sum(checked)} tiles; expected {expected} for {declared_sets} declared set(s)")
    if checked[context.winning_tile] == 0:
        raise ValueError("the winning tile must be part of the concealed hand")

    splits = _decompositions(checked, 5 - declared_sets)
    if not splits:
        raise ValueError("hand is not a winning hand")

    pre_win = list(checked)
    pre_win[context.winning_tile] -= 1
    single_wait = len(_winning_kinds(pre_win, declared_sets)) == 1

    meld_tiles = [tile for kind, start in meld_sets for tile in ((start, start, start) if kind == "tri" else (start, start + 1, start + 2))]
    every_tile = [tile for tile in range(34) if checked[tile]] + meld_tiles + [tile for tile, _ in kongs]
    suits_present = {tile // 9 for tile in every_tile if tile < 27}
    honors_present = any(tile >= 27 for tile in every_tile)

    best: ScoreResult | None = None
    for pair, concealed_sets in splits:
        result = _score_decomposition(
            pair, concealed_sets, meld_sets, context, single_wait, suits_present, honors_present,
            kong_sets, concealed_kong_count, open_kong_count,
        )
        if best is None or result.total_tai > best.total_tai:
            best = result
    assert best is not None
    return best
