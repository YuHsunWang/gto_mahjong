"""Fast shanten calculation for regular Taiwanese mahjong hands."""

from __future__ import annotations

from functools import lru_cache

from .tiles import validate_counts


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


@lru_cache(maxsize=None)
def _numeric_options(suit: tuple[int, ...]) -> tuple[tuple[int, int, int], ...]:
    """All (melds, incomplete melds, heads) extractable from one numeric suit."""
    @lru_cache(maxsize=None)
    def walk(state: tuple[int, ...]) -> frozenset[tuple[int, int, int]]:
        try:
            index = next(i for i, count in enumerate(state) if count)
        except StopIteration:
            return frozenset({(0, 0, 0)})

        next_states: list[tuple[tuple[int, ...], tuple[int, int, int]]] = []
        reduced = list(state)
        reduced[index] -= 1
        next_states.append((tuple(reduced), (0, 0, 0)))  # leave it unused
        if state[index] >= 2:
            reduced = list(state)
            reduced[index] -= 2
            next_states.append((tuple(reduced), (0, 1, 0)))  # a pair used as taatsu
            next_states.append((tuple(reduced), (0, 0, 1)))  # a pair used as the head
        if state[index] >= 3:
            reduced = list(state)
            reduced[index] -= 3
            next_states.append((tuple(reduced), (1, 0, 0)))
        if index <= 6 and state[index + 1] and state[index + 2]:
            reduced = list(state)
            reduced[index] -= 1
            reduced[index + 1] -= 1
            reduced[index + 2] -= 1
            next_states.append((tuple(reduced), (1, 0, 0)))
        if index <= 7 and state[index + 1]:
            reduced = list(state)
            reduced[index] -= 1
            reduced[index + 1] -= 1
            next_states.append((tuple(reduced), (0, 1, 0)))
        if index <= 6 and state[index + 2]:
            reduced = list(state)
            reduced[index] -= 1
            reduced[index + 2] -= 1
            next_states.append((tuple(reduced), (0, 1, 0)))

        outcomes: set[tuple[int, int, int]] = set()
        for remainder, addition in next_states:
            for melds, taatsu, head in walk(remainder):
                outcomes.add((melds + addition[0], taatsu + addition[1], head + addition[2]))
        return frozenset(outcomes)

    return tuple(walk(suit))


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


def shanten(counts: tuple[int, ...] | list[int], melds_declared: int = 0) -> int:
    """Return regular-hand shanten (-1 for a complete 17-tile hand)."""
    checked, _ = _validate_hand(counts, melds_declared)
    groups = (
        _numeric_options(checked[0:9]),
        _numeric_options(checked[9:18]),
        _numeric_options(checked[18:27]),
        _honor_options(checked[27:34]),
    )
    states = {(melds_declared, 0, 0)}
    for group in groups:
        states = {
            (melds + add_melds, taatsu + add_taatsu, heads + add_heads)
            for melds, taatsu, heads in states
            for add_melds, add_taatsu, add_heads in group
            if melds + add_melds <= 5
        }

    best = 10
    for melds, taatsu, heads in states:
        usable_taatsu = min(taatsu, 5 - melds)
        candidate = 10 - 2 * melds - usable_taatsu - min(heads, 1)
        best = min(best, candidate)
    return best
