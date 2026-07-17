"""Monte Carlo self-draw simulation for Taiwanese mahjong hands."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from .shanten import shanten
from .tiles import validate_counts
from .ukeire import ukeire


@dataclass(frozen=True)
class SimResult:
    """Cumulative tenpai and self-draw win probabilities from a simulation."""

    sims: int
    turns: int
    tenpai_by_turn: list[float]
    win_by_turn: list[float]
    p_tenpai: float
    p_win: float


def _validate_positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be an integer greater than or equal to 1")


def win_probability(
    counts: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 5000,
    seed: int | None = None,
) -> SimResult:
    """Estimate cumulative tenpai and self-draw win chances over ``turns`` draws.

    A starting tenpai hand is counted in the turn-one tenpai total, so the
    returned curves have exactly one entry for each simulated draw.
    """
    _validate_positive_int(turns, "turns")
    _validate_positive_int(sims, "sims")

    hand = validate_counts(counts)
    # This reuses M2's exact concealed-size and visible-tile validation.
    ukeire(hand, melds_declared, visible)
    seen = (0,) * 34 if visible is None else validate_counts(visible)
    pool = [
        tile
        for tile in range(34)
        for _ in range(4 - hand[tile] - seen[tile])
    ]
    if len(pool) < turns:
        raise ValueError(f"unseen pool has {len(pool)} tiles; expected at least {turns}")

    @lru_cache(maxsize=None)
    def cached_shanten(current: tuple[int, ...]) -> int:
        return shanten(current, melds_declared)

    @lru_cache(maxsize=None)
    def greedy_discard(current: tuple[int, ...]) -> tuple[int, int]:
        """Return the same first choice as ``discard_analysis(current)[0]``.

        M2 ranks by resulting shanten before ukeire. Calculate ukeire only
        for the candidates tied at the best shanten; the other candidates
        cannot affect the first result and dominate simulation runtime.
        """
        candidates: list[tuple[int, tuple[int, ...]]] = []
        best_shanten = 11
        for tile, count in enumerate(current):
            if not count:
                continue
            reduced = list(current)
            reduced[tile] -= 1
            after = tuple(reduced)
            after_shanten = cached_shanten(after)
            if after_shanten < best_shanten:
                best_shanten = after_shanten
                candidates = [(tile, after)]
            elif after_shanten == best_shanten:
                candidates.append((tile, after))

        best_tile = -1
        best_total = -1
        for tile, after in candidates:
            total = 0
            for draw, count in enumerate(after):
                if count == 4:
                    continue
                next_hand = list(after)
                next_hand[draw] += 1
                if cached_shanten(tuple(next_hand)) < best_shanten:
                    total += 4 - after[draw] - seen[draw]
            if total > best_total or (total == best_total and (best_tile == -1 or tile < best_tile)):
                best_tile = tile
                best_total = total
        return best_tile, best_shanten

    rng = random.Random(seed)
    tenpai_counts = [0] * turns
    win_counts = [0] * turns
    initial_shanten = cached_shanten(hand)

    for _ in range(sims):
        draws = pool[:]
        rng.shuffle(draws)
        current = hand
        first_tenpai = 1 if initial_shanten <= 0 else 0
        first_win = 0

        for index, tile in enumerate(draws[:turns], start=1):
            drawn = list(current)
            drawn[tile] += 1
            current = tuple(drawn)
            if cached_shanten(current) == -1:
                first_tenpai = first_tenpai or index
                first_win = index
                break

            discard, after_shanten = greedy_discard(current)
            reduced = list(current)
            reduced[discard] -= 1
            current = tuple(reduced)
            if not first_tenpai and after_shanten <= 0:
                first_tenpai = index

        for index in range(turns):
            if first_tenpai and first_tenpai <= index + 1:
                tenpai_counts[index] += 1
            if first_win and first_win <= index + 1:
                win_counts[index] += 1

    tenpai_by_turn = [count / sims for count in tenpai_counts]
    win_by_turn = [count / sims for count in win_counts]
    return SimResult(
        sims=sims,
        turns=turns,
        tenpai_by_turn=tenpai_by_turn,
        win_by_turn=win_by_turn,
        p_tenpai=tenpai_by_turn[-1],
        p_win=win_by_turn[-1],
    )
