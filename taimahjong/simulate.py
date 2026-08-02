"""Monte Carlo self-draw simulation for Taiwanese mahjong hands."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

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


@dataclass(frozen=True)
class WinningTrial:
    """One self-draw win observed by :func:`winning_trials`."""

    hand: tuple[int, ...]
    winning_tile: int
    turn: int
    trial: int = 0


@dataclass(frozen=True)
class TrialTrace:
    """One complete draw stream under a deterministic discard policy."""

    trial: int
    win: WinningTrial | None


DiscardPolicy = Callable[
    [tuple[int, ...], tuple[int, ...], tuple[int, ...], int],
    int,
]


def _validate_positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be an integer greater than or equal to 1")


@lru_cache(maxsize=200_000)
def _cached_shanten(current: tuple[int, ...], melds_declared: int) -> int:
    return shanten(current, melds_declared)


@lru_cache(maxsize=200_000)
def _greedy_discard(
    current: tuple[int, ...],
    remaining_counts: tuple[int, ...],
    melds_declared: int,
) -> tuple[int, int]:
    """Return the M2 first choice using the trial's current unseen copies.

    The remaining-count tuple is part of the cache key.  It preserves the
    common-random-number draw stream while preventing a later policy decision
    from treating an earlier own discard as drawable again.
    """
    candidates: list[tuple[int, tuple[int, ...]]] = []
    best_shanten = 11
    for tile, count in enumerate(current):
        if not count:
            continue
        reduced = list(current)
        reduced[tile] -= 1
        after = tuple(reduced)
        after_shanten = _cached_shanten(after, melds_declared)
        if after_shanten < best_shanten:
            best_shanten = after_shanten
            candidates = [(tile, after)]
        elif after_shanten == best_shanten:
            candidates.append((tile, after))

    best_tile = -1
    best_total = -1
    for tile, after in candidates:
        total = 0
        for draw, copies in enumerate(remaining_counts):
            if copies <= 0:
                continue
            next_hand = list(after)
            next_hand[draw] += 1
            if _cached_shanten(tuple(next_hand), melds_declared) < best_shanten:
                total += copies
        if total > best_total or (total == best_total and (best_tile == -1 or tile < best_tile)):
            best_tile = tile
            best_total = total
    return best_tile, best_shanten


@dataclass(frozen=True)
class _RolloutResult:
    first_tenpai_turns: tuple[int, ...]
    wins: tuple[WinningTrial, ...]
    trials: tuple[TrialTrace, ...]


def _assert_physical_state(
    hand: tuple[int, ...],
    visible: list[int],
    remaining_counts: list[int],
) -> None:
    assert all(
        hand[tile] + visible[tile] + remaining_counts[tile] == 4
        for tile in range(34)
    ), "trial tile copies were not conserved"


def _rollout(
    counts: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 5000,
    seed: int | None = None,
    discard_policy: DiscardPolicy | None = None,
) -> _RolloutResult:
    """Run the single shared greedy rollout used by both public summaries."""
    _validate_positive_int(turns, "turns")
    _validate_positive_int(sims, "sims")
    hand = validate_counts(counts)
    ukeire(hand, melds_declared, visible)
    seen = (0,) * 34 if visible is None else validate_counts(visible)
    initial_remaining = tuple(4 - hand[tile] - seen[tile] for tile in range(34))
    pool = [tile for tile, copies in enumerate(initial_remaining) for _ in range(copies)]
    if len(pool) < turns:
        raise ValueError(f"unseen pool has {len(pool)} tiles; expected at least {turns}")

    rng = random.Random(seed)
    initial_shanten = _cached_shanten(hand, melds_declared)
    tenpai_turns: list[int] = []
    wins: list[WinningTrial] = []
    traces: list[TrialTrace] = []
    for trial in range(sims):
        draws = pool[:]
        rng.shuffle(draws)
        current = hand
        dynamic_visible = list(seen)
        remaining_counts = list(initial_remaining)
        _assert_physical_state(current, dynamic_visible, remaining_counts)
        first_tenpai = 1 if initial_shanten <= 0 else 0
        winning: WinningTrial | None = None

        for turn, tile in enumerate(draws[:turns], start=1):
            assert remaining_counts[tile] > 0
            remaining_counts[tile] -= 1
            drawn = list(current)
            drawn[tile] += 1
            current = tuple(drawn)
            _assert_physical_state(current, dynamic_visible, remaining_counts)
            if _cached_shanten(current, melds_declared) == -1:
                first_tenpai = first_tenpai or turn
                winning = WinningTrial(current, tile, turn, trial)
                wins.append(winning)
                break

            if discard_policy is None:
                discard, after_shanten = _greedy_discard(
                    current, tuple(remaining_counts), melds_declared,
                )
            else:
                discard = discard_policy(
                    current,
                    tuple(remaining_counts),
                    tuple(dynamic_visible),
                    melds_declared,
                )
                if not 0 <= discard < 34 or not current[discard]:
                    raise ValueError("discard policy returned a tile not present in the hand")
                reduced_for_shanten = list(current)
                reduced_for_shanten[discard] -= 1
                after_shanten = _cached_shanten(tuple(reduced_for_shanten), melds_declared)
            reduced = list(current)
            reduced[discard] -= 1
            current = tuple(reduced)
            dynamic_visible[discard] += 1
            _assert_physical_state(current, dynamic_visible, remaining_counts)
            if not first_tenpai and after_shanten <= 0:
                first_tenpai = turn
        tenpai_turns.append(first_tenpai)
        traces.append(TrialTrace(trial, winning))
    return _RolloutResult(tuple(tenpai_turns), tuple(wins), tuple(traces))


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
    rollout = _rollout(counts, turns, melds_declared, visible, sims, seed)
    tenpai_counts = [
        sum(bool(first) and first <= turn for first in rollout.first_tenpai_turns)
        for turn in range(1, turns + 1)
    ]
    win_counts = [
        sum(win.turn <= turn for win in rollout.wins)
        for turn in range(1, turns + 1)
    ]
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


def winning_trials(
    counts: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 5000,
    seed: int | None = None,
) -> tuple[WinningTrial, ...]:
    """Return final winning hands and draw turns for deterministic trials.

    This is a view of the exact shared rollout used by
    :func:`win_probability`; a discarded tile is not returned to the wall.
    """
    return _rollout(counts, turns, melds_declared, visible, sims, seed).wins


def policy_trials(
    counts: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 5000,
    seed: int | None = None,
    discard_policy: DiscardPolicy | None = None,
) -> tuple[TrialTrace, ...]:
    """Return every trial trace under one deterministic policy.

    Passing the same ``seed`` to different policies preserves the same shuffled
    draw streams (CRN); only the policy's discards differ.
    """
    return _rollout(
        counts, turns, melds_declared, visible, sims, seed, discard_policy,
    ).trials
