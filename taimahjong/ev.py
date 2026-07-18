"""Tai-unit EV approximations with survival-discounted self-draw attack."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from math import ceil, comb

from .calibration import Calibration
from .danger import OpponentView, _flush_suit, danger_score, fold_score, tenpai_score
from .scoring import BASE_UNITS, WinContext, score_hand
from .shanten import shanten
from .simulate import winning_trials
from .tiles import validate_counts
from .ukeire import discard_analysis


# UNCALIBRATED visible-state opponent-value and fallback-risk constants.
OPPONENT_DECLARED_TAI = 8
OPPONENT_DRAGON_TRIPLET_TAI = 1
OPPONENT_FLUSH_READ_TAI = 4
OPPONENT_ALL_TRIPLETS_TAI = 4
# Dealing into the dealer settles the bilateral premium (莊 + 連莊拉莊), so the
# defender's loss-magnitude estimate mirrors scoring.DEALER_TAI /
# STREAK_TAI_PER_WIN. Kept as separate constants so the defensive read can be
# tuned (or zeroed for an unaware-baseline experiment) without touching the
# settlement rule; read live as module attributes.
OPPONENT_DEALER_TAI = 1
OPPONENT_STREAK_TAI_PER_WIN = 2
DEAL_IN_FALLBACK_RATE = 0.02
DECLARED_FACTOR = 2.0
BASELINE_TENPAI_RATE = 0.25

# M7 survival/draw constants.  They are deliberately UNCALIBRATED heuristics.
BASE_OPPONENT_HAZARD = 0.03
FOLD_HAZARD_CUTOFF = 0.60
DRAW_VALUE = 0.0


@dataclass(frozen=True)
class WinValueContext:
    """A score template plus optional known declared melds for EV scoring."""

    context: WinContext
    melds: tuple[tuple[int, int, int], ...] = ()


@dataclass(frozen=True)
class WinValueEstimate:
    p_win: float
    mean_value_units: float | None
    expected_win_ev: float
    survival_adjusted_p_win: float = 0.0
    discounted_attack_ev: float = 0.0
    p_draw: float = 0.0
    net_ev: float = 0.0


@dataclass(frozen=True)
class EVRankEntry:
    discard: int
    p_win: float
    mean_win_value: float | None
    attack_ev: float
    opponent_losses: tuple[float, ...]
    risk_ev: float
    net_ev: float
    survival_adjusted_p_win: float = 0.0
    p_draw: float = 0.0
    is_fold: bool = False
    label: str | None = None


@dataclass(frozen=True)
class DeclarationAdvice:
    declared: WinValueEstimate
    undeclared: WinValueEstimate
    should_declare: bool


def remaining_draws(own_hand: tuple[int, ...] | list[int], visible: tuple[int, ...] | list[int]) -> int:
    """Approximate this seat's remaining draws from the live-wall tile count.

    Taiwanese mahjong reserves a 16-tile dead wall.  Public tiles and this
    seat's concealed hand have already left the live wall, and turns rotate
    among four seats, so this returns ``ceil(live_wall / 4)``.
    """
    hand = validate_counts(own_hand)
    seen = validate_counts(visible)
    live_wall = 136 - 16 - sum(hand) - sum(seen)
    return max(0, ceil(live_wall / 4))


def opponent_hazards(opponents: tuple[OpponentView, ...] | list[OpponentView]) -> tuple[float, ...]:
    """Return fixed per-turn opponent win hazards from current public reads."""
    views = tuple(opponents)
    hazards: list[float] = []
    for index, opponent in enumerate(views):
        others = [
            entry if isinstance(entry, int) else entry.tile
            for other_index, other in enumerate(views)
            if other_index != index
            for entry in other.river
        ]
        folded = fold_score(opponent, others) >= FOLD_HAZARD_CUTOFF
        tenpai = 1.0 if opponent.declared_at is not None else tenpai_score(opponent, len(opponent.river)).score
        multiplier = min(3.0, max(0.25, tenpai / BASELINE_TENPAI_RATE))
        hazards.append(0.0 if folded else BASE_OPPONENT_HAZARD * multiplier)
    return tuple(hazards)


def survival_by_turn(turns: int, opponents: tuple[OpponentView, ...] | list[OpponentView]) -> tuple[float, ...]:
    """Return survival through each of our draws, using independent hazards."""
    if turns < 0:
        raise ValueError("turns must be non-negative")
    per_turn = min(1.0, sum(opponent_hazards(opponents)))
    survival = 1.0
    values: list[float] = []
    for _ in range(turns):
        survival = max(0.0, survival * (1.0 - per_turn))
        values.append(survival)
    return tuple(values)


def _template(template: WinContext | WinValueContext | None) -> tuple[WinContext, tuple[tuple[int, int, int], ...]]:
    if template is None:
        return WinContext(winning_tile=0), ()
    if isinstance(template, WinValueContext):
        return template.context, template.melds
    if isinstance(template, WinContext):
        return template, ()
    raise ValueError("context_template must be WinContext or WinValueContext")


def _score_value(hand: tuple[int, ...], winning_tile: int, template: WinContext | WinValueContext | None, migi: bool | None = None) -> int:
    # The acting player's OWN dealer/streak premium is honored via the template
    # (self-draw here). Honest approximation: a non-dealer winner collects the
    # bilateral premium only when the payer is the dealer (ron off dealer, or
    # the dealer's tsumo leg), which this symmetric win estimate does NOT model
    # — so a non-dealer's win EV is under-counted by at most P/3 of one win
    # (P = DEALER_TAI + STREAK_TAI_PER_WIN*streak). Modeling it needs a
    # per-target win distribution; deferred, and flagged in docs/experiments.
    context, melds = _template(template)
    return score_hand(
        hand,
        list(melds),
        replace(context, winning_tile=winning_tile, self_draw=True, migi_declared=context.migi_declared if migi is None else migi),
    ).value_units


def estimate_win_value(
    counts16: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
) -> WinValueEstimate:
    """Estimate self-draw P(win), conditional win value, and their product."""
    if turns == 0:
        return WinValueEstimate(0.0, None, 0.0)
    wins = winning_trials(counts16, turns, melds_declared, visible, sims, seed)
    if not wins:
        return WinValueEstimate(0.0, None, 0.0)
    values = [_score_value(trial.hand, trial.winning_tile, context_template) for trial in wins]
    mean = sum(values) / len(values)
    return WinValueEstimate(len(wins) / sims, mean, len(wins) / sims * mean)


def _discounted_win_estimate(
    counts16: tuple[int, ...],
    turns: int,
    melds_declared: int,
    visible: tuple[int, ...],
    sims: int,
    seed: int | None,
    context_template: WinContext | WinValueContext | None,
    survival: tuple[float, ...],
) -> WinValueEstimate:
    """Score simulated first-win increments and weight each by survival."""
    if not turns:
        return WinValueEstimate(0.0, None, 0.0, p_draw=1.0, net_ev=DRAW_VALUE)
    wins = winning_trials(counts16, turns, melds_declared, visible, sims, seed)
    values = [_score_value(trial.hand, trial.winning_tile, context_template) for trial in wins]
    if not wins:
        return WinValueEstimate(0.0, None, 0.0, p_draw=survival[-1], net_ev=survival[-1] * DRAW_VALUE)
    mean = sum(values) / len(values)
    raw = WinValueEstimate(len(wins) / sims, mean, len(wins) / sims * mean)
    discounted_p_win = sum(survival[trial.turn - 1] for trial in wins) / sims
    discounted_attack = sum(survival[trial.turn - 1] * value for trial, value in zip(wins, values)) / sims
    # Preserve exact pre-M7 arithmetic in the no-hazard case.
    if all(value == 1.0 for value in survival):
        discounted_p_win = raw.p_win
        discounted_attack = raw.expected_win_ev
    p_draw = survival[-1] * (1.0 - raw.p_win)
    return replace(
        raw,
        survival_adjusted_p_win=discounted_p_win,
        discounted_attack_ev=discounted_attack,
        p_draw=p_draw,
        net_ev=discounted_attack + p_draw * DRAW_VALUE,
    )


def opponent_value_estimate(opponent: OpponentView) -> float:
    """Return an UNCALIBRATED tai-unit value from public opponent state only."""
    opponent.validate()
    tai = OPPONENT_DECLARED_TAI if opponent.declared_at is not None else 0
    tai += OPPONENT_DRAGON_TRIPLET_TAI * sum(
        meld[0] == meld[1] == meld[2] and meld[0] in (31, 32, 33) for meld in opponent.melds
    )
    if _flush_suit(opponent) is not None:
        tai += OPPONENT_FLUSH_READ_TAI
    if len(opponent.melds) >= 3 and all(meld[0] == meld[1] == meld[2] for meld in opponent.melds):
        tai += OPPONENT_ALL_TRIPLETS_TAI
    if opponent.is_dealer:
        tai += OPPONENT_DEALER_TAI + OPPONENT_STREAK_TAI_PER_WIN * opponent.dealer_streak
    return float(BASE_UNITS + tai)


def deal_in_ev(
    tile: int,
    opponent: OpponentView,
    visible: tuple[int, ...] | list[int],
    own_hand: tuple[int, ...] | list[int],
    calibration: Calibration | None,
) -> float:
    """Approximate expected tai-unit loss for one discard against one opponent."""
    assessment = danger_score(tile, opponent, visible, own_hand)
    if opponent.declared_at is not None and "declared_safe" in assessment.modifiers:
        return 0.0
    probability = calibration.deal_in_probability(assessment.score) if calibration else None
    if probability is None:
        probability = DEAL_IN_FALLBACK_RATE * assessment.score / 9.0
    probability = min(0.35, max(0.0, probability))
    if opponent.declared_at is not None:
        factor = DECLARED_FACTOR
    else:
        factor = min(3.0, max(0.25, tenpai_score(opponent, len(opponent.river)).score / BASELINE_TENPAI_RATE))
    return probability * factor * opponent_value_estimate(opponent)


def ev_rank(
    counts17: tuple[int, ...] | list[int],
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    visible: tuple[int, ...] | list[int],
    melds_declared: int = 0,
    turns: int = 10,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
    calibration: Calibration | None = None,
    top_k: int = 5,
) -> list[EVRankEntry]:
    """Rank an efficient candidate set by self-draw EV less deal-in losses."""
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    hand = validate_counts(counts17)
    seen = validate_counts(visible)
    views = tuple(opponents)
    analyses = discard_analysis(hand, melds_declared, seen)
    ranked_danger: list[tuple[object, float]] = []
    for analysis in analyses:
        post = list(hand)
        post[analysis.discard] -= 1
        max_danger = max((danger_score(analysis.discard, view, seen, tuple(post)).score for view in views), default=0.0)
        ranked_danger.append((analysis, max_danger))
    selected = ranked_danger[:top_k]
    baseline = min((danger for _, danger in selected), default=0.0)
    selected.extend(item for item in ranked_danger[top_k:] if item[1] < baseline)
    selected = selected[: top_k + 2]

    survival = survival_by_turn(turns, views)
    # CRN (common random numbers) reduces variance in differences between
    # candidates: identical randomness cancels shared sampling noise. Each
    # absolute EV still has Monte Carlo error that only more sims reduces.
    base_seed = random.randrange(2**64) if seed is None else seed
    entries: list[EVRankEntry] = []
    for analysis, _ in selected:
        post = list(hand)
        post[analysis.discard] -= 1
        attack = _discounted_win_estimate(
            tuple(post), turns, melds_declared, seen, sims, base_seed, context_template, survival,
        )
        losses = tuple(deal_in_ev(analysis.discard, view, seen, tuple(post), calibration) for view in views)
        risk = sum(losses)
        entries.append(EVRankEntry(
            analysis.discard, attack.p_win, attack.mean_value_units, attack.discounted_attack_ev,
            losses, risk, attack.net_ev - risk, attack.survival_adjusted_p_win, attack.p_draw,
        ))
    minimum_risk = min((entry.risk_ev for entry in entries), default=0.0)
    terminal_survival = survival[-1] if survival else 1.0
    entries.append(EVRankEntry(
        -1, 0.0, None, 0.0, (), minimum_risk,
        terminal_survival * DRAW_VALUE - minimum_risk, 0.0, terminal_survival,
        True, "fold",
    ))
    return sorted(entries, key=lambda entry: (entry.is_fold, -entry.net_ev, entry.discard))


def evaluate_discard(
    counts17: tuple[int, ...] | list[int],
    discard: int,
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    visible: tuple[int, ...] | list[int],
    melds_declared: int = 0,
    turns: int = 10,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
    calibration: Calibration | None = None,
) -> EVRankEntry:
    """Net-EV of one discard using the exact discounted-attack, survival, and
    CRN-seed logic of :func:`ev_rank`'s per-candidate body.

    This lets a caller re-estimate an already-selected candidate at a higher
    ``sims`` budget while sharing the ranking's CRN ``seed`` — so the difference
    between two re-estimated candidates stays variance-reduced, but each one's
    absolute Monte Carlo error shrinks ~``sqrt(cheap_sims / sims)``. It does not
    re-rank or re-simulate the whole candidate set.
    """
    hand = validate_counts(counts17)
    seen = validate_counts(visible)
    views = tuple(opponents)
    survival = survival_by_turn(turns, views)
    base_seed = random.randrange(2**64) if seed is None else seed
    post = list(hand)
    post[discard] -= 1
    attack = _discounted_win_estimate(
        tuple(post), turns, melds_declared, seen, sims, base_seed, context_template, survival,
    )
    losses = tuple(deal_in_ev(discard, view, seen, tuple(post), calibration) for view in views)
    risk = sum(losses)
    return EVRankEntry(
        discard, attack.p_win, attack.mean_value_units, attack.discounted_attack_ev,
        losses, risk, attack.net_ev - risk, attack.survival_adjusted_p_win, attack.p_draw,
    )


def declaration_ev(
    counts16: tuple[int, ...] | list[int],
    visible: tuple[int, ...] | list[int] | None,
    turns: int,
    context_template: WinContext | WinValueContext | None = None,
    sims: int = 400,
    seed: int | None = None,
    opponents: tuple[OpponentView, ...] | list[OpponentView] = (),
) -> DeclarationAdvice:
    """Compare exact locked-migi EV with the simulated upgrade-allowed branch."""
    hand = validate_counts(counts16)
    if shanten(hand) != 0:
        raise ValueError("declaration advisor requires a tenpai hand (shanten 0)")
    seen = (0,) * 34 if visible is None else validate_counts(visible)
    if any(hand[tile] + seen[tile] > 4 for tile in range(34)):
        raise ValueError("hand and visible tiles cannot contain more than four copies of a tile kind")
    pool = sum(4 - hand[tile] - seen[tile] for tile in range(34))
    if turns < 0 or turns > pool:
        raise ValueError("turns must be between 0 and the unseen pool size")
    waits: list[tuple[int, int, int]] = []
    for tile in range(34):
        remaining = 4 - hand[tile] - seen[tile]
        if not remaining:
            continue
        completed = list(hand)
        completed[tile] += 1
        if shanten(tuple(completed)) == -1:
            waits.append((tile, remaining, _score_value(tuple(completed), tile, context_template, migi=True)))
    winning = sum(remaining for _, remaining, _ in waits)
    p_win = 0.0 if not winning or not turns else 1.0 - comb(pool - winning, turns) / comb(pool, turns)
    mean = None if not winning else sum(remaining * value for _, remaining, value in waits) / winning
    raw_declared_ev = p_win * mean if mean is not None else 0.0
    survival = survival_by_turn(turns, opponents)
    declared_attack = 0.0
    declared_adjusted_p_win = 0.0
    for turn in range(1, turns + 1):
        no_prior_win = comb(pool - winning, turn - 1) / comb(pool, turn - 1)
        increment = no_prior_win * winning / (pool - turn + 1)
        declared_adjusted_p_win += survival[turn - 1] * increment
        declared_attack += survival[turn - 1] * no_prior_win * sum(remaining * value for _, remaining, value in waits) / (pool - turn + 1)
    if all(value == 1.0 for value in survival):
        declared_adjusted_p_win = p_win
        declared_attack = raw_declared_ev
    declared_draw = (survival[-1] if survival else 1.0) * (1.0 - p_win)
    declared = WinValueEstimate(
        p_win, mean, raw_declared_ev, declared_adjusted_p_win, declared_attack,
        declared_draw, declared_attack + declared_draw * DRAW_VALUE,
    )
    base_context, melds = _template(context_template)
    undeclared_template = WinValueContext(replace(base_context, migi_declared=False), melds)
    undeclared = _discounted_win_estimate(hand, turns, 0, seen, sims, seed, undeclared_template, survival)
    return DeclarationAdvice(declared, undeclared, declared.net_ev > undeclared.net_ev)
