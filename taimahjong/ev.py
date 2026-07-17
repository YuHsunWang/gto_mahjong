"""M5b tai-unit expected-value approximations.

Attack EV models self-draw wins only.  Deal-in calibration is a marginal
bot-state probability, so combining it with M4a reads and this visible-state
opponent value is deliberately an approximation; no draw (流局) term exists.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import comb

from .calibration import Calibration
from .danger import OpponentView, _flush_suit, danger_score, tenpai_score
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
DEAL_IN_FALLBACK_RATE = 0.02
DECLARED_FACTOR = 2.0
BASELINE_TENPAI_RATE = 0.25


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


@dataclass(frozen=True)
class EVRankEntry:
    discard: int
    p_win: float
    mean_win_value: float | None
    attack_ev: float
    opponent_losses: tuple[float, ...]
    risk_ev: float
    net_ev: float


@dataclass(frozen=True)
class DeclarationAdvice:
    declared: WinValueEstimate
    undeclared: WinValueEstimate
    should_declare: bool


def _template(template: WinContext | WinValueContext | None) -> tuple[WinContext, tuple[tuple[int, int, int], ...]]:
    if template is None:
        return WinContext(winning_tile=0), ()
    if isinstance(template, WinValueContext):
        return template.context, template.melds
    if isinstance(template, WinContext):
        return template, ()
    raise ValueError("context_template must be WinContext or WinValueContext")


def _score_value(hand: tuple[int, ...], winning_tile: int, template: WinContext | WinValueContext | None, migi: bool | None = None) -> int:
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
    wins = winning_trials(counts16, turns, melds_declared, visible, sims, seed)
    if not wins:
        return WinValueEstimate(0.0, None, 0.0)
    values = [_score_value(trial.hand, trial.winning_tile, context_template) for trial in wins]
    mean = sum(values) / len(values)
    return WinValueEstimate(len(wins) / sims, mean, len(wins) / sims * mean)


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

    entries: list[EVRankEntry] = []
    for analysis, _ in selected:
        post = list(hand)
        post[analysis.discard] -= 1
        candidate_seed = None if seed is None else seed + analysis.discard * 1_000_003
        attack = estimate_win_value(tuple(post), turns, melds_declared, seen, sims, candidate_seed, context_template)
        losses = tuple(deal_in_ev(analysis.discard, view, seen, tuple(post), calibration) for view in views)
        risk = sum(losses)
        entries.append(EVRankEntry(analysis.discard, attack.p_win, attack.mean_value_units, attack.expected_win_ev, losses, risk, attack.expected_win_ev - risk))
    return sorted(entries, key=lambda entry: (-entry.net_ev, entry.discard))


def declaration_ev(
    counts16: tuple[int, ...] | list[int],
    visible: tuple[int, ...] | list[int] | None,
    turns: int,
    context_template: WinContext | WinValueContext | None = None,
    sims: int = 400,
    seed: int | None = None,
) -> DeclarationAdvice:
    """Compare exact locked-migi EV with the simulated upgrade-allowed branch."""
    hand = validate_counts(counts16)
    if shanten(hand) != 0:
        raise ValueError("declaration advisor requires a tenpai hand (shanten 0)")
    seen = (0,) * 34 if visible is None else validate_counts(visible)
    if any(hand[tile] + seen[tile] > 4 for tile in range(34)):
        raise ValueError("hand and visible tiles cannot contain more than four copies of a tile kind")
    pool = sum(4 - hand[tile] - seen[tile] for tile in range(34))
    if turns < 1 or turns > pool:
        raise ValueError("turns must be between 1 and the unseen pool size")
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
    p_win = 0.0 if not winning else 1.0 - comb(pool - winning, turns) / comb(pool, turns)
    mean = None if not winning else sum(remaining * value for _, remaining, value in waits) / winning
    declared = WinValueEstimate(p_win, mean, p_win * mean if mean is not None else 0.0)
    base_context, melds = _template(context_template)
    undeclared_template = WinValueContext(replace(base_context, migi_declared=False), melds)
    undeclared = estimate_win_value(hand, turns, 0, seen, sims, seed, undeclared_template)
    return DeclarationAdvice(declared, undeclared, declared.expected_win_ev > undeclared.expected_win_ev)
