"""Tai-unit EV approximations with survival-discounted self-draw attack."""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import ceil, comb

from .calibration import Calibration
from .danger import OpponentView, RiverEntry, _flush_suit, danger_score, fold_score, tenpai_score
from .moments import SampleMoments
from .scoring import BASE_UNITS, DEFAULT_SCHEME, ScoringScheme, WinContext, score_hand
from .shanten import shanten
from .simulate import DiscardPolicy, TrialTrace, policy_trials, winning_trials
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
SCREENING_EFFECT_MARGIN = 0.10


@dataclass(frozen=True)
class WinValueContext:
    """A score template plus optional known declared melds for EV scoring."""

    context: WinContext
    melds: tuple[tuple[int, int, int], ...] = ()
    kongs: tuple[tuple[int, bool], ...] = ()


@dataclass(frozen=True)
class WinValueEstimate:
    p_win: float
    mean_value_units: float | None
    expected_win_ev: float
    survival_adjusted_p_win: float = 0.0
    discounted_attack_ev: float = 0.0
    p_draw: float = 0.0
    net_ev: float = 0.0
    sample_count: int = 0
    win_count: int = 0
    value_sum: float = 0.0
    value_sum_squares: float = 0.0
    standard_error: float = 0.0
    ci95_low: float = 0.0
    ci95_high: float = 0.0
    trial_values: tuple[float, ...] = field(default=(), repr=False, compare=False)
    traces: tuple[TrialTrace, ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class FoldActionPlan:
    """Executable first discard plus the deterministic defense principles."""

    first_discard: int
    safe_inventory: tuple[int, ...]
    principles: tuple[str, ...]


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
    sample_count: int = 0
    win_count: int = 0
    value_sum: float = 0.0
    value_sum_squares: float = 0.0
    standard_error: float = 0.0
    ci95_low: float = 0.0
    ci95_high: float = 0.0
    action_plan: FoldActionPlan | None = None
    trial_values: tuple[float, ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class DeclarationAdvice:
    declared: WinValueEstimate
    undeclared: WinValueEstimate
    should_declare: bool


@dataclass(frozen=True)
class TileAccounting:
    """Typed observable tiles for wall accounting versus tile availability.

    ``out_of_hands`` contains river tiles and any other tiles that are no
    longer in a player's fixed holding. ``revealed_holdings`` contains open
    melds/kongs: they remain useful for ukeire and danger, but must not be
    deducted again after the three opponents' 48-tile holding allowance.
    """

    out_of_hands: tuple[int, ...] | list[int] = (0,) * 34
    revealed_holdings: tuple[int, ...] | list[int] = (0,) * 34

    def __post_init__(self) -> None:
        outside = validate_counts(self.out_of_hands)
        holdings = validate_counts(self.revealed_holdings)
        if any(outside[tile] + holdings[tile] > 4 for tile in range(34)):
            raise ValueError("observable tiles cannot contain more than four copies of a tile kind")
        object.__setattr__(self, "out_of_hands", outside)
        object.__setattr__(self, "revealed_holdings", holdings)

    @property
    def visible(self) -> tuple[int, ...]:
        return tuple(
            self.out_of_hands[tile] + self.revealed_holdings[tile]
            for tile in range(34)
        )


def _with_moments(
    estimate: WinValueEstimate,
    values: tuple[float, ...],
    *,
    win_count: int,
    traces: tuple[TrialTrace, ...] = (),
) -> WinValueEstimate:
    moments = SampleMoments.from_values(values)
    low, high = moments.ci95
    return replace(
        estimate,
        sample_count=moments.n,
        win_count=win_count,
        value_sum=moments.total,
        value_sum_squares=moments.sum_squares,
        standard_error=moments.standard_error,
        ci95_low=low,
        ci95_high=high,
        trial_values=values,
        traces=traces,
    )


def paired_delta_moments(first: EVRankEntry, second: EVRankEntry) -> SampleMoments:
    """Paired top-gap moments from candidates evaluated under the same CRN."""
    if not first.trial_values or len(first.trial_values) != len(second.trial_values):
        return SampleMoments()
    return SampleMoments.from_values(
        left - right
        for left, right in zip(first.trial_values, second.trial_values)
    )


def remaining_draws(
    own_hand: tuple[int, ...] | list[int],
    accounting: TileAccounting | tuple[int, ...] | list[int] | None = None,
    *,
    wall_remaining: int | None = None,
) -> int:
    """Approximate this seat's remaining draws from the live-wall tile count.

    An explicit live-wall count is authoritative.  Otherwise Taiwanese
    mahjong reserves a 16-tile dead wall; this seat's concealed hand and the
    three opponents' fixed 48-tile holdings are already deducted, so only
    ``TileAccounting.out_of_hands`` is additionally removed. Revealed melds
    stay inside those holdings and do not shorten the wall a second time.
    """
    hand = validate_counts(own_hand)
    if wall_remaining is not None:
        if not isinstance(wall_remaining, int) or isinstance(wall_remaining, bool) or wall_remaining < 0:
            raise ValueError("wall_remaining must be a non-negative integer")
        return ceil(wall_remaining / 4)
    if accounting is None:
        tiles = TileAccounting()
    elif isinstance(accounting, TileAccounting):
        tiles = accounting
    else:
        # Backward-compatible strict meaning: a bare count tuple is out of all
        # hands (river/other public tiles), never an opponent meld.
        tiles = TileAccounting(accounting)
    if any(hand[tile] + tiles.visible[tile] > 4 for tile in range(34)):
        raise ValueError("hand and observable tiles cannot contain more than four copies of a tile kind")
    live_wall = 136 - 16 - sum(hand) - 3 * 16 - sum(tiles.out_of_hands)
    return max(0, ceil(live_wall / 4))


def opponent_hazards(
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
) -> tuple[float, ...]:
    """Return fixed per-turn opponent win hazards from current public reads."""
    views = tuple(opponents)
    hazards: list[float] = []
    for index, opponent in enumerate(views):
        others = [entry if isinstance(entry, int) else entry.tile for entry in own_river]
        others.extend(
            entry if isinstance(entry, int) else entry.tile
            for other_index, other in enumerate(views)
            if other_index != index
            for entry in other.river
        )
        folded = fold_score(opponent, others) >= FOLD_HAZARD_CUTOFF
        tenpai = 1.0 if opponent.declared_at is not None else tenpai_score(opponent, len(opponent.river)).score
        multiplier = min(3.0, max(0.25, tenpai / BASELINE_TENPAI_RATE))
        hazards.append(0.0 if folded else BASE_OPPONENT_HAZARD * multiplier)
    return tuple(hazards)


def survival_by_turn(
    turns: int,
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
) -> tuple[float, ...]:
    """Return survival through each of our draws, using independent hazards."""
    if turns < 0:
        raise ValueError("turns must be non-negative")
    per_turn = min(1.0, sum(opponent_hazards(opponents, own_river)))
    survival = 1.0
    values: list[float] = []
    for _ in range(turns):
        survival = max(0.0, survival * (1.0 - per_turn))
        values.append(survival)
    return tuple(values)


def _template(
    template: WinContext | WinValueContext | None,
) -> tuple[WinContext, tuple[tuple[int, int, int], ...], tuple[tuple[int, bool], ...]]:
    if template is None:
        return WinContext(winning_tile=0), (), ()
    if isinstance(template, WinValueContext):
        return template.context, template.melds, template.kongs
    if isinstance(template, WinContext):
        return template, (), ()
    raise ValueError("context_template must be WinContext or WinValueContext")


def _score_value(hand: tuple[int, ...], winning_tile: int, template: WinContext | WinValueContext | None, migi: bool | None = None, scheme: ScoringScheme = DEFAULT_SCHEME) -> int:
    # The acting player's OWN dealer/streak premium is honored via the template
    # (self-draw here). Honest approximation: a non-dealer winner collects the
    # bilateral premium only when the payer is the dealer (ron off dealer, or
    # the dealer's tsumo leg), which this symmetric win estimate does NOT model
    # — so a non-dealer's win EV is under-counted by at most P/3 of one win
    # (P = DEALER_TAI + STREAK_TAI_PER_WIN*streak). Modeling it needs a
    # per-target win distribution; deferred, and flagged in docs/experiments.
    context, melds, kongs = _template(template)
    return score_hand(
        hand,
        list(melds),
        replace(context, winning_tile=winning_tile, self_draw=True, migi_declared=context.migi_declared if migi is None else migi),
        kongs=kongs,
    ).value_in(scheme)


def estimate_win_value(
    counts16: tuple[int, ...] | list[int],
    turns: int,
    melds_declared: int = 0,
    visible: tuple[int, ...] | list[int] | None = None,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
    scheme: ScoringScheme = DEFAULT_SCHEME,
) -> WinValueEstimate:
    """Estimate self-draw P(win), conditional win value, and their product."""
    if turns == 0:
        return WinValueEstimate(0.0, None, 0.0)
    wins = winning_trials(counts16, turns, melds_declared, visible, sims, seed)
    scored = {
        trial.trial: float(_score_value(
            trial.hand, trial.winning_tile, context_template, scheme=scheme,
        ))
        for trial in wins
    }
    values = tuple(scored.get(trial, 0.0) for trial in range(sims))
    mean = None if not wins else sum(scored.values()) / len(wins)
    estimate = WinValueEstimate(
        len(wins) / sims,
        mean,
        sum(scored.values()) / sims,
        net_ev=sum(values) / sims,
    )
    return _with_moments(estimate, values, win_count=len(wins))


def _discounted_win_estimate(
    counts16: tuple[int, ...],
    turns: int,
    melds_declared: int,
    visible: tuple[int, ...],
    sims: int,
    seed: int | None,
    context_template: WinContext | WinValueContext | None,
    survival: tuple[float, ...],
    scheme: ScoringScheme = DEFAULT_SCHEME,
    discard_policy: DiscardPolicy | None = None,
) -> WinValueEstimate:
    """Score simulated first-win increments and weight each by survival."""
    if not turns:
        values = (float(DRAW_VALUE),) * sims
        return _with_moments(
            WinValueEstimate(0.0, None, 0.0, p_draw=1.0, net_ev=DRAW_VALUE),
            values,
            win_count=0,
        )
    traces = policy_trials(
        counts16, turns, melds_declared, visible, sims, seed, discard_policy,
    )
    wins = tuple(trace.win for trace in traces if trace.win is not None)
    scored = {
        trial.trial: float(_score_value(
            trial.hand, trial.winning_tile, context_template, scheme=scheme,
        ))
        for trial in wins
    }
    mean = None if not wins else sum(scored.values()) / len(wins)
    raw = WinValueEstimate(
        len(wins) / sims,
        mean,
        sum(scored.values()) / sims,
    )
    discounted_p_win = sum(
        survival[trial.turn - 1] for trial in wins
    ) / sims
    discounted_attack = sum(
        survival[trial.turn - 1] * scored[trial.trial]
        for trial in wins
    ) / sims
    # Preserve exact pre-M7 arithmetic in the no-hazard case.
    if all(value == 1.0 for value in survival):
        discounted_p_win = raw.p_win
        discounted_attack = raw.expected_win_ev
    p_draw = survival[-1] * (1.0 - raw.p_win)
    trial_values = tuple(
        (
            survival[trace.win.turn - 1] * scored[trace.trial]
            if trace.win is not None
            else survival[-1] * DRAW_VALUE
        )
        for trace in traces
    )
    estimate = replace(
        raw,
        survival_adjusted_p_win=discounted_p_win,
        discounted_attack_ev=discounted_attack,
        p_draw=p_draw,
        net_ev=discounted_attack + p_draw * DRAW_VALUE,
    )
    return _with_moments(
        estimate, trial_values, win_count=len(wins), traces=traces,
    )


def opponent_value_estimate(opponent: OpponentView, scheme: ScoringScheme = DEFAULT_SCHEME) -> float:
    """Return an UNCALIBRATED chip-unit value from public opponent state only.

    Uses the same 底/台 ``scheme`` as the attack side, so a scheme swap rescales
    a deal-in loss consistently with a win's value.
    """
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
    return float(scheme.value(tai))


def deal_in_ev(
    tile: int,
    opponent: OpponentView,
    visible: tuple[int, ...] | list[int],
    own_hand: tuple[int, ...] | list[int],
    calibration: Calibration | None,
    scheme: ScoringScheme = DEFAULT_SCHEME,
) -> float:
    """Approximate expected chip-unit loss for one discard against one opponent."""
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
    return probability * factor * opponent_value_estimate(opponent, scheme)


def _discard_losses(
    tile: int,
    hand_after: tuple[int, ...],
    visible: tuple[int, ...],
    opponents: tuple[OpponentView, ...],
    calibration: Calibration | None,
    scheme: ScoringScheme,
) -> tuple[float, ...]:
    return tuple(
        deal_in_ev(tile, opponent, visible, hand_after, calibration, scheme)
        for opponent in opponents
    )


def _is_genbutsu(
    tile: int,
    hand_after: tuple[int, ...],
    visible: tuple[int, ...],
    opponents: tuple[OpponentView, ...],
) -> bool:
    declared = [opponent for opponent in opponents if opponent.declared_at is not None]
    return bool(declared) and all(
        "declared_safe" in danger_score(
            tile, opponent, visible, hand_after,
        ).modifiers
        for opponent in declared
    )


def _fold_choice(
    current: tuple[int, ...],
    visible: tuple[int, ...],
    opponents: tuple[OpponentView, ...],
    calibration: Calibration | None,
    scheme: ScoringScheme,
) -> int:
    """Genbutsu-first, then minimum conditional loss with safe inventory."""
    if not opponents:
        return next(tile for tile, count in enumerate(current) if count)
    candidates: list[tuple[int, float, bool]] = []
    for tile, count in enumerate(current):
        if not count:
            continue
        post = list(current)
        post[tile] -= 1
        after = tuple(post)
        losses = _discard_losses(
            tile, after, visible, opponents, calibration, scheme,
        )
        loss = sum(losses)
        genbutsu = _is_genbutsu(tile, after, visible, opponents)
        candidates.append((tile, loss, genbutsu))
    if not candidates:
        raise ValueError("fold policy requires at least one discardable tile")
    safe_copies = sum(
        current[tile] for tile, loss, _ in candidates if loss == 0.0
    )
    ranked = [
        (
            (
                0 if genbutsu else 1,
                loss,
                -(safe_copies - (1 if loss == 0.0 else 0)),
                tile,
            ),
            tile,
        )
        for tile, loss, genbutsu in candidates
    ]
    return min(ranked)[1]


def _fold_policy(
    opponents: tuple[OpponentView, ...],
    calibration: Calibration | None,
    scheme: ScoringScheme,
) -> DiscardPolicy:
    @lru_cache(maxsize=50_000)
    def cached(
        current: tuple[int, ...],
        visible: tuple[int, ...],
    ) -> int:
        return _fold_choice(current, visible, opponents, calibration, scheme)

    def choose(
        current: tuple[int, ...],
        _remaining: tuple[int, ...],
        visible: tuple[int, ...],
        _melds_declared: int,
    ) -> int:
        return cached(current, visible)

    return choose


def _future_policy_losses(
    traces: tuple[TrialTrace, ...],
    opponents: tuple[OpponentView, ...],
    calibration: Calibration | None,
    scheme: ScoringScheme,
    survival: tuple[float, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if not traces:
        return (0.0,) * len(opponents), ()
    if not opponents:
        return (), (0.0,) * len(traces)
    per_opponent = [0.0] * len(opponents)
    per_trial: list[float] = []
    cache: dict[
        tuple[int, tuple[int, ...], tuple[int, ...]],
        tuple[float, ...],
    ] = {}
    for trace in traces:
        trial_loss = 0.0
        for step in trace.discards:
            weight = survival[step.turn - 1]
            key = (step.tile, step.hand, step.visible)
            losses = cache.get(key)
            if losses is None:
                losses = _discard_losses(
                    step.tile,
                    step.hand,
                    step.visible,
                    opponents,
                    calibration,
                    scheme,
                )
                cache[key] = losses
            for index, loss in enumerate(losses):
                per_opponent[index] += weight * loss
                trial_loss += weight * loss
        per_trial.append(trial_loss)
    return (
        tuple(total / len(traces) for total in per_opponent),
        tuple(per_trial),
    )


def _entry_from_policy(
    discard: int,
    attack: WinValueEstimate,
    immediate_losses: tuple[float, ...],
    future_losses: tuple[float, ...],
    future_trial_losses: tuple[float, ...],
    *,
    is_fold: bool = False,
    label: str | None = None,
    action_plan: FoldActionPlan | None = None,
) -> EVRankEntry:
    opponent_losses = tuple(
        immediate + future
        for immediate, future in zip(immediate_losses, future_losses)
    )
    risk = sum(opponent_losses)
    if attack.trial_values:
        net_values = tuple(
            value - sum(immediate_losses) - future
            for value, future in zip(attack.trial_values, future_trial_losses)
        )
        moments = SampleMoments.from_values(net_values)
        low, high = moments.ci95
    else:
        net_values = ()
        moments = SampleMoments()
        low = high = attack.net_ev - risk
    return EVRankEntry(
        discard,
        attack.p_win,
        attack.mean_value_units,
        attack.discounted_attack_ev,
        opponent_losses,
        risk,
        attack.net_ev - risk,
        attack.survival_adjusted_p_win,
        attack.p_draw,
        is_fold,
        label,
        moments.n,
        attack.win_count,
        moments.total,
        moments.sum_squares,
        moments.standard_error,
        low,
        high,
        action_plan,
        net_values,
    )


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
    scheme: ScoringScheme = DEFAULT_SCHEME,
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
    declaration_eligible: bool = False,
    exhaustive: bool = False,
    reference_fixed_top_k: bool = False,
) -> list[EVRankEntry]:
    """Rank candidates by policy EV.

    The production default uses two-stage confidence-bound screening.
    ``exhaustive`` is an opt-in reference mode that evaluates every legal discard under one
    CRN seed. ``reference_fixed_top_k`` reproduces the pre-MJ-008 selector for
    benchmark attribution only; neither reference flag is used by production.
    """
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
    survival = survival_by_turn(turns, views, own_river)
    # CRN (common random numbers) reduces variance in differences between
    # candidates: identical randomness cancels shared sampling noise. Each
    # absolute EV still has Monte Carlo error that only more sims reduces.
    base_seed = random.randrange(2**64) if seed is None else seed

    def evaluate(analysis, budget: int) -> EVRankEntry:
        post = list(hand)
        post[analysis.discard] -= 1
        attack_visible = list(seen)
        attack_visible[analysis.discard] += 1
        if declaration_eligible and shanten(tuple(post), melds_declared) == 0:
            advice = declaration_ev(
                tuple(post), tuple(attack_visible), turns, context_template, budget,
                base_seed, views, scheme, own_river,
            )
            attack = advice.declared if advice.should_declare else advice.undeclared
        else:
            attack = _discounted_win_estimate(
                tuple(post), turns, melds_declared, tuple(attack_visible), budget, base_seed, context_template, survival, scheme,
            )
        immediate = _discard_losses(
            analysis.discard, tuple(post), seen, views, calibration, scheme,
        )
        future, future_trials = _future_policy_losses(
            attack.traces, views, calibration, scheme, survival,
        )
        return _entry_from_policy(
            analysis.discard, attack, immediate, future, future_trials,
        )

    if exhaustive:
        entries = [evaluate(analysis, sims) for analysis, _ in ranked_danger]
    elif reference_fixed_top_k:
        selected = ranked_danger[:top_k]
        baseline = min((danger for _, danger in selected), default=0.0)
        selected.extend(
            item for item in ranked_danger[top_k:]
            if item[1] < baseline
        )
        entries = [
            evaluate(analysis, sims)
            for analysis, _ in selected[:top_k + 2]
        ]
    else:
        # MJ-008 reference corpus missed top-1 under fixed top-k.  Stage one
        # therefore gives every legal discard a small same-CRN pilot. Stage two
        # spends the requested budget only on candidates whose conservative
        # confidence bound can still beat the best lower bound.
        pilot_sims = min(sims, 4)
        pilots = [
            (analysis, evaluate(analysis, pilot_sims))
            for analysis, _ in ranked_danger
        ]

        def radius(entry: EVRankEntry) -> float:
            # A floor prevents a zero-win pilot from claiming zero uncertainty.
            floor = 0.50 / max(1.0, pilot_sims ** 0.5)
            return 1.959963984540054 * max(entry.standard_error, floor)

        best_lower = max(
            entry.net_ev - radius(entry)
            for _, entry in pilots
        )
        screened = [
            (analysis, entry)
            for analysis, entry in pilots
            if entry.net_ev + radius(entry) + SCREENING_EFFECT_MARGIN >= best_lower
        ]
        if len(screened) < min(top_k, len(pilots)):
            screened = sorted(
                pilots,
                key=lambda item: (-item[1].net_ev, item[1].discard),
            )[:min(top_k, len(pilots))]
        entries = (
            [entry for _, entry in screened]
            if pilot_sims == sims
            else [evaluate(analysis, sims) for analysis, _ in screened]
        )

    entries.append(evaluate_fold_policy(
        hand,
        views,
        seen,
        melds_declared,
        turns,
        sims,
        base_seed,
        context_template,
        calibration,
        scheme,
        own_river,
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
    scheme: ScoringScheme = DEFAULT_SCHEME,
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
    declaration_eligible: bool = False,
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
    survival = survival_by_turn(turns, views, own_river)
    base_seed = random.randrange(2**64) if seed is None else seed
    post = list(hand)
    post[discard] -= 1
    attack_visible = list(seen)
    attack_visible[discard] += 1
    if declaration_eligible and shanten(tuple(post), melds_declared) == 0:
        advice = declaration_ev(
            tuple(post), tuple(attack_visible), turns, context_template, sims,
            base_seed, views, scheme, own_river,
        )
        attack = advice.declared if advice.should_declare else advice.undeclared
    else:
        attack = _discounted_win_estimate(
            tuple(post), turns, melds_declared, tuple(attack_visible), sims, base_seed, context_template, survival, scheme,
        )
    immediate = _discard_losses(
        discard, tuple(post), seen, views, calibration, scheme,
    )
    future, future_trials = _future_policy_losses(
        attack.traces, views, calibration, scheme, survival,
    )
    return _entry_from_policy(
        discard, attack, immediate, future, future_trials,
    )


def evaluate_fold_policy(
    counts17: tuple[int, ...] | list[int],
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    visible: tuple[int, ...] | list[int],
    melds_declared: int = 0,
    turns: int = 10,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
    calibration: Calibration | None = None,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
) -> EVRankEntry:
    """Evaluate the executable defense policy at a chosen MC budget."""
    hand = validate_counts(counts17)
    seen = validate_counts(visible)
    views = tuple(opponents)
    survival = survival_by_turn(turns, views, own_river)
    base_seed = random.randrange(2**64) if seed is None else seed
    discard = _fold_choice(hand, seen, views, calibration, scheme)
    post = list(hand)
    post[discard] -= 1
    attack_visible = list(seen)
    attack_visible[discard] += 1
    attack = _discounted_win_estimate(
        tuple(post),
        turns,
        melds_declared,
        tuple(attack_visible),
        sims,
        base_seed,
        context_template,
        survival,
        scheme,
        _fold_policy(views, calibration, scheme),
    )
    immediate = _discard_losses(
        discard, tuple(post), seen, views, calibration, scheme,
    )
    future, future_trials = _future_policy_losses(
        attack.traces, views, calibration, scheme, survival,
    )
    safe_inventory = tuple(
        tile
        for tile, count in enumerate(hand)
        if count
        and sum(_discard_losses(
            tile,
            tuple(
                count - 1 if index == tile else value
                for index, value in enumerate(hand)
            ),
            seen,
            views,
            calibration,
            scheme,
        )) == 0.0
    )
    return _entry_from_policy(
        discard,
        attack,
        immediate,
        future,
        future_trials,
        is_fold=True,
        label="defense_policy",
        action_plan=FoldActionPlan(
            discard,
            safe_inventory,
            (
                "genbutsu_first",
                "minimum_conditional_loss_each_turn",
                "preserve_safe_inventory",
            ),
        ),
    )


def declaration_ev(
    counts16: tuple[int, ...] | list[int],
    visible: tuple[int, ...] | list[int] | None,
    turns: int,
    context_template: WinContext | WinValueContext | None = None,
    sims: int = 400,
    seed: int | None = None,
    opponents: tuple[OpponentView, ...] | list[OpponentView] = (),
    scheme: ScoringScheme = DEFAULT_SCHEME,
    own_river: tuple[RiverEntry | int, ...] | list[RiverEntry | int] = (),
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
            waits.append((tile, remaining, _score_value(tuple(completed), tile, context_template, migi=True, scheme=scheme)))
    winning = sum(remaining for _, remaining, _ in waits)
    p_win = 0.0 if not winning or not turns else 1.0 - comb(pool - winning, turns) / comb(pool, turns)
    mean = None if not winning else sum(remaining * value for _, remaining, value in waits) / winning
    raw_declared_ev = p_win * mean if mean is not None else 0.0
    survival = survival_by_turn(turns, opponents, own_river)
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
    base_context, melds, kongs = _template(context_template)
    undeclared_template = WinValueContext(replace(base_context, migi_declared=False), melds, kongs)
    undeclared = _discounted_win_estimate(hand, turns, 0, seen, sims, seed, undeclared_template, survival, scheme)
    return DeclarationAdvice(declared, undeclared, declared.net_ev > undeclared.net_ev)
