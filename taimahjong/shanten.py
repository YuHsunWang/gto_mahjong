"""Fast shanten calculation for regular Taiwanese mahjong hands."""

from __future__ import annotations

from functools import lru_cache

from .tiles import validate_counts


# A numeric suit has nine counts in 0..4, so base five is a collision-free
# compact key for its complete state space.
_SUIT_RADIX = 5
_SUIT_POWERS = tuple(_SUIT_RADIX ** index for index in range(9))

# Outcome bit positions are ((melds * 6 + taatsu) * 2 + has_head).  These
# masks enforce the structural five-meld limit before shifting a state.
_HEADLESS_OUTCOMES = sum(
    1 << ((melds * 6 + taatsu) * 2)
    for melds in range(6)
    for taatsu in range(6)
)
_TAATSU_ROOM_OUTCOMES = sum(
    3 << ((melds * 6 + taatsu) * 2)
    for melds in range(6)
    for taatsu in range(5)
)
_MELD_ROOM_OUTCOMES = sum(
    3 << ((melds * 6 + taatsu) * 2)
    for melds in range(5)
    for taatsu in range(6)
)


def _validate_hand(counts: tuple[int, ...] | list[int], melds_declared: int) -> tuple[tuple[int, ...], int]:
    checked = validate_counts(counts)
    if not isinstance(melds_declared, int) or isinstance(melds_declared, bool) or not 0 <= melds_declared <= 5:
        raise ValueError("melds_declared must be an integer between 0 and 5")
    concealed_size = sum(checked)
    allowed = {16 - 3 * melds_declared, 17 - 3 * melds_declared}
    if concealed_size not in allowed:
        expected = " or ".join(str(size) for size in sorted(allowed))
        raise ValueError(
            f"concealed hand has {concealed_size} tiles; expected {expected} for {melds_declared} declared meld(s)"
        )
    return checked, concealed_size


def _honor_options(honors: tuple[int, ...]) -> tuple[tuple[int, int, int], ...]:
    """Honors can only form triplets and pairs."""
    options = {(0, 0, 0)}
    for count in honors:
        choices = [(0, 0, 0)]
        if count >= 2:
            choices.extend(((0, 1, 0), (0, 0, 1)))
        if count >= 3:
            choices.append((1, 0, 0))
        options = {
            (melds + add_melds, taatsu + add_taatsu, heads + add_heads)
            for melds, taatsu, heads in options
            for add_melds, add_taatsu, add_heads in choices
        }
    return tuple(options)


@lru_cache(maxsize=None)
def _group_profile(
    options: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, int, int], ...]:
    """Keep only the best taatsu count for each meld/head state."""
    best: dict[tuple[int, int], int] = {}
    for melds, taatsu, heads in options:
        key = (melds, min(1, heads))
        best[key] = max(best.get(key, -1), taatsu)
    return tuple(
        (melds, best[(melds, has_head)], has_head)
        for melds, has_head in sorted(best)
    )


@lru_cache(maxsize=None)
def _combine_profiles(
    left: tuple[tuple[int, int, int], ...],
    right: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, int, int], ...]:
    """Combine canonical group profiles, memoizing repeated suit shapes."""
    best: dict[tuple[int, int], int] = {}
    for melds, taatsu, has_head in left:
        for add_melds, add_taatsu, add_head in right:
            total_melds = melds + add_melds
            if total_melds > 5:
                continue
            key = (total_melds, min(1, has_head + add_head))
            best[key] = max(best.get(key, -1), taatsu + add_taatsu)
    return tuple(
        (melds, best[(melds, has_head)], has_head)
        for melds, has_head in sorted(best)
    )


@lru_cache(maxsize=None)
def _numeric_profile(suit: tuple[int, ...]) -> tuple[tuple[int, int, int], ...]:
    key = sum(count * power for count, power in zip(suit, _SUIT_POWERS))
    outcomes = _numeric_outcomes(key)
    profile = []
    for melds in range(6):
        for has_head in range(2):
            for taatsu in range(5, -1, -1):
                bit = (melds * 6 + taatsu) * 2 + has_head
                if outcomes & (1 << bit):
                    profile.append((melds, taatsu, has_head))
                    break
    return tuple(profile)


@lru_cache(maxsize=None)
def _numeric_outcomes(key: int) -> int:
    """Return a compact bitset of every useful decomposition of one suit."""
    if not key:
        return 1
    for index, power in enumerate(_SUIT_POWERS):
        count = key // power % _SUIT_RADIX
        if count:
            break

    outcomes = _numeric_outcomes(key - power)  # leave one tile unused
    if count >= 2:
        reduced = _numeric_outcomes(key - 2 * power)
        outcomes |= (reduced & _TAATSU_ROOM_OUTCOMES) << 2
        outcomes |= (reduced & _HEADLESS_OUTCOMES) << 1
    if count >= 3:
        reduced = _numeric_outcomes(key - 3 * power)
        outcomes |= (reduced & _MELD_ROOM_OUTCOMES) << 12
    if index <= 6:
        next_count = key // _SUIT_POWERS[index + 1] % _SUIT_RADIX
        next_next_count = key // _SUIT_POWERS[index + 2] % _SUIT_RADIX
        if next_count and next_next_count:
            reduced = _numeric_outcomes(
                key - power - _SUIT_POWERS[index + 1] - _SUIT_POWERS[index + 2]
            )
            outcomes |= (reduced & _MELD_ROOM_OUTCOMES) << 12
        if next_next_count:
            reduced = _numeric_outcomes(key - power - _SUIT_POWERS[index + 2])
            outcomes |= (reduced & _TAATSU_ROOM_OUTCOMES) << 2
    if index <= 7 and key // _SUIT_POWERS[index + 1] % _SUIT_RADIX:
        reduced = _numeric_outcomes(key - power - _SUIT_POWERS[index + 1])
        outcomes |= (reduced & _TAATSU_ROOM_OUTCOMES) << 2
    return outcomes


@lru_cache(maxsize=None)
def _honor_profile(honors: tuple[int, ...]) -> tuple[tuple[int, int, int], ...]:
    return _group_profile(_honor_options(honors))


def _shanten_unchecked(counts: tuple[int, ...], melds_declared: int) -> int:
    """Exact shanten for an internally validated concealed hand."""
    groups = (
        _numeric_profile(counts[0:9]),
        _numeric_profile(counts[9:18]),
        _numeric_profile(counts[18:27]),
        _honor_profile(counts[27:34]),
    )
    profile = groups[0]
    for group in groups[1:]:
        profile = _combine_profiles(profile, group)
    best = max(
        2 * (melds + melds_declared)
        + min(taatsu, 5 - melds - melds_declared)
        + has_head
        for melds, taatsu, has_head in profile
        if melds + melds_declared <= 5
    )
    return 10 - best


def shanten(counts: tuple[int, ...] | list[int], melds_declared: int = 0) -> int:
    """Return regular-hand shanten (-1 for a complete 17-tile hand)."""
    checked, _ = _validate_hand(counts, melds_declared)
    return _shanten_unchecked(checked, melds_declared)
