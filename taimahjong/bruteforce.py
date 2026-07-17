"""Deliberately simple reference shanten search used for cross-validation."""

from __future__ import annotations

from functools import lru_cache

from .shanten import _validate_hand


@lru_cache(maxsize=None)
def _is_complete(counts: tuple[int, ...], melds_declared: int) -> bool:
    """Memoized recursive checker for 5-meld-plus-pair hands."""
    needed_melds = 5 - melds_declared

    @lru_cache(maxsize=None)
    def remove_melds(state: tuple[int, ...], melds_left: int) -> bool:
        if melds_left == 0:
            return not any(state)
        try:
            index = next(i for i, count in enumerate(state) if count)
        except StopIteration:
            return False
        if state[index] >= 3:
            reduced = list(state)
            reduced[index] -= 3
            if remove_melds(tuple(reduced), melds_left - 1):
                return True
        if index < 27 and index % 9 <= 6 and state[index + 1] and state[index + 2]:
            reduced = list(state)
            reduced[index] -= 1
            reduced[index + 1] -= 1
            reduced[index + 2] -= 1
            if remove_melds(tuple(reduced), melds_left - 1):
                return True
        return False

    for head in range(34):
        if counts[head] >= 2:
            reduced = list(counts)
            reduced[head] -= 2
            if remove_melds(tuple(reduced), needed_melds):
                return True
    return False


@lru_cache(maxsize=None)
def _is_tenpai(counts: tuple[int, ...], melds_declared: int) -> bool:
    return any(
        counts[tile] < 4 and _is_complete(counts[:tile] + (counts[tile] + 1,) + counts[tile + 1 :], melds_declared)
        for tile in range(34)
    )


def _exchange_neighbors(counts: tuple[int, ...]):
    """Generate unique hands reachable with exactly one tile exchange."""
    for removed, amount in enumerate(counts):
        if not amount:
            continue
        after_remove = list(counts)
        after_remove[removed] -= 1
        for added, remaining in enumerate(after_remove):
            if added != removed and remaining < 4:
                next_counts = list(after_remove)
                next_counts[added] += 1
                yield tuple(next_counts)


def bruteforce_shanten(counts: tuple[int, ...] | list[int], melds_declared: int = 0) -> int:
    """Return exact shanten by breadth-first search over tile exchanges.

    The searched target is a win for an after-draw hand and tenpai for a
    between-turn hand.  Search depth is finite because every target has the
    same concealed tile count as the input.
    """
    checked, concealed_size = _validate_hand(counts, melds_declared)
    after_draw = concealed_size == 17 - 3 * melds_declared
    target = _is_complete if after_draw else _is_tenpai
    if target(checked, melds_declared):
        return -1 if after_draw else 0

    frontier = {checked}
    seen = set(frontier)
    exchanges = 0
    while frontier:
        exchanges += 1
        next_frontier = set()
        for state in frontier:
            for neighbor in _exchange_neighbors(state):
                if neighbor in seen:
                    continue
                if target(neighbor, melds_declared):
                    return exchanges - 1 if after_draw else exchanges
                seen.add(neighbor)
                next_frontier.add(neighbor)
        frontier = next_frontier
    raise AssertionError("every valid hand should be reachable from a winning shape")
