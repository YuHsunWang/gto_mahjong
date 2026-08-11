"""Tai-unit EV ranking from coherent four-seat terminal rollouts.

Each production ranking sample is one mutually exclusive game terminal and
``net_ev`` is the mean signed payment to the acting seat.  The injectable
discard policy is an unvalidated opponent-model choice; reference-corpus
agreement certifies terminal/settlement/aggregation machinery, not its realism.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import permutations
from math import ceil, comb
from typing import TYPE_CHECKING, Sequence

from .calibration import Calibration
from .config import DEFAULT_RULES, RulesConfig
from .danger import (
    KongLike,
    MeldLike,
    OpponentView,
    RiverEntry,
    _flush_suit,
    assess_validated_danger,
    danger_score,
    fold_score,
    meld_tiles,
    tenpai_score,
)
from .moments import ClusteredSampleMoments, SampleMoments
from .scoring import BASE_UNITS, DEFAULT_SCHEME, ScoringScheme, WinContext, score_hand
from .shanten import _shanten_unchecked, shanten
from .simulate import (
    DiscardPolicy,
    TrialTrace,
    policy_trials,
    winning_trials,
)
from .tiles import validate_counts
from .ukeire import discard_analysis

if TYPE_CHECKING:
    from .rollout import ContinuationDiscardPolicy
    from .rollout import DiscardPolicy as TerminalDiscardPolicy
    from .rollout import TerminalResult
    from .selfplay import Player


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
PRODUCTION_HIDDEN_WORLD_STRATA = 32


@dataclass(frozen=True)
class WinValueContext:
    """A score template plus optional known declared melds for EV scoring."""

    context: WinContext
    melds: tuple[MeldLike, ...] = ()
    kongs: tuple[KongLike, ...] = ()


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
    standard_error: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    trial_values: tuple[float, ...] = field(default=(), repr=False, compare=False)


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
    standard_error: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    action_plan: FoldActionPlan | None = None
    trial_values: tuple[float, ...] = field(default=(), repr=False, compare=False)
    trial_strata: tuple[int, ...] = field(default=(), repr=False, compare=False)


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
) -> WinValueEstimate:
    moments = SampleMoments.from_values(values)
    interval = moments.ci95
    low, high = (None, None) if interval is None else interval
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
    )


def paired_delta_moments(first: EVRankEntry, second: EVRankEntry) -> SampleMoments:
    """Descriptive paired top-gap moments under CRN after selecting the pair."""
    if not first.trial_values or len(first.trial_values) != len(second.trial_values):
        return SampleMoments(post_selection=True)
    deltas = tuple(
        left - right
        for left, right in zip(first.trial_values, second.trial_values)
    )
    if first.trial_strata and first.trial_strata == second.trial_strata:
        return ClusteredSampleMoments.from_clustered_values(
            deltas,
            first.trial_strata,
            post_selection=True,
        )
    return SampleMoments.from_values(deltas, post_selection=True)


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
) -> tuple[WinContext, tuple[MeldLike, ...], tuple[KongLike, ...]]:
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
    """Estimate gross self-draw value, never a decision's signed ``net_ev``.

    This compatibility helper has no production caller.  It models only the
    acting hand drawing a win, so ``expected_win_ev`` and the legacy ``net_ev``
    field are always non-negative gross attack values: neither includes ron,
    opponent tsumo, draws, or four-seat settlement.  They must not be compared
    with :func:`ev_rank` or :func:`evaluate_pass`, whose ``net_ev`` is mean
    signed payment from mutually exclusive terminals.
    """
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
    return _with_moments(estimate, trial_values, win_count=len(wins))


def opponent_value_estimate(opponent: OpponentView, scheme: ScoringScheme = DEFAULT_SCHEME) -> float:
    """Return an UNCALIBRATED chip-unit value from public opponent state only.

    Uses the same 底/台 ``scheme`` as the attack side, so a scheme swap rescales
    a deal-in loss consistently with a win's value.
    """
    opponent.validate()
    normalized_melds = tuple(meld_tiles(meld) for meld in opponent.melds)
    tai = OPPONENT_DECLARED_TAI if opponent.declared_at is not None else 0
    tai += OPPONENT_DRAGON_TRIPLET_TAI * sum(
        meld[0] == meld[1] == meld[2] and meld[0] in (31, 32, 33) for meld in normalized_melds
    )
    if _flush_suit(opponent) is not None:
        tai += OPPONENT_FLUSH_READ_TAI
    if len(normalized_melds) >= 3 and all(meld[0] == meld[1] == meld[2] for meld in normalized_melds):
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
    """Approximate expected chip-unit loss for one discard against one opponent.

    The deal-in probability is taken from calibration exactly as
    ``_calibrated_ron`` takes it, with no opponent-state multiplier on top. The
    table is fitted against ``danger_score`` alone, which carries no tenpai
    signal, so its rows are already marginal over the opponent's tenpai state;
    scaling them again double-counts it. It also matters that this function and
    the rollout agree: the fold policy picks its discard here but is *scored* by
    the terminal rollout, so a different risk model in the two places has the
    defense optimising something it is not graded on.

    The uncalibrated fallback is the exception. ``DEAL_IN_FALLBACK_RATE`` scaled
    by raw danger contains no opponent-state information at all, so there the
    tenpai/declaration factor is the only such signal available and is kept.
    """
    assessment = danger_score(tile, opponent, visible, own_hand)
    if opponent.declared_at is not None and "declared_safe" in assessment.modifiers:
        return 0.0
    probability = calibration.deal_in_probability(assessment.score) if calibration else None
    calibrated = probability is not None
    if probability is None:
        probability = DEAL_IN_FALLBACK_RATE * assessment.score / 9.0
    probability = min(0.35, max(0.0, probability))
    if calibrated:
        factor = 1.0
    elif opponent.declared_at is not None:
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
    """Genbutsu-first, then minimum loss, retaining repeated safe tiles."""
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
    ranked = [
        (
            (
                0 if genbutsu else 1,
                loss,
                -current[tile] if loss == 0.0 else 0,
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
) -> ContinuationDiscardPolicy:
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



@dataclass(frozen=True)
class _TrialWorld:
    players: tuple[Player, Player, Player, Player]
    wall: tuple[int, ...]
    terminal_seed: int | None = None
    wall_order: tuple[int, ...] | None = None
    hidden_stratum: int | None = None
    ron_value_hands: tuple[
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
    ] = (None, None, None, None)


class _OrderedWallRandom:
    """Minimal randrange source that makes resolve_terminal draw one order."""

    def __init__(self, wall: tuple[int, ...], order: tuple[int, ...]):
        remaining = [0] * 34
        for tile in wall:
            remaining[tile] += 1
        choices = []
        stops = []
        for tile in order:
            if not remaining[tile]:
                raise ValueError("wall order is not a permutation of the wall")
            stops.append(sum(remaining))
            choices.append(sum(remaining[:tile]))
            remaining[tile] -= 1
        self._choices = iter(choices)
        self._stops = iter(stops)

    def randrange(self, stop: int) -> int:
        expected = next(self._stops)
        if stop != expected:
            raise ValueError("terminal rollout consumed an unexpected wall size")
        return next(self._choices)


@lru_cache(maxsize=200_000)
def _production_shanten(
    hand: tuple[int, ...],
    melds_declared: int,
) -> int:
    """Fast exact shanten for validated internal rollout hands."""
    return _shanten_unchecked(hand, melds_declared)


@lru_cache(maxsize=100_000)
def _production_discard_analysis(
    hand17: tuple[int, ...],
    melds_declared: int,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """Cache the hand-only part of the rollout policy's ukeire comparison."""
    candidates: list[tuple[int, tuple[int, ...]]] = []
    best_shanten = 11
    for tile, count in enumerate(hand17):
        if not count:
            continue
        reduced = list(hand17)
        reduced[tile] -= 1
        after = tuple(reduced)
        after_shanten = _production_shanten(after, melds_declared)
        if after_shanten < best_shanten:
            best_shanten = after_shanten
            candidates = [(tile, after)]
        elif after_shanten == best_shanten:
            candidates.append((tile, after))

    analyzed = []
    for tile, after in candidates:
        improving = []
        for draw, count in enumerate(after):
            if count >= 4:
                continue
            next_hand = list(after)
            next_hand[draw] += 1
            if _production_shanten(tuple(next_hand), melds_declared) < best_shanten:
                improving.append(draw)
        analyzed.append((tile, tuple(improving)))
    return tuple(analyzed)


def _production_discard_policy(
    hand17: tuple[int, ...],
    remaining: tuple[int, ...],
    melds_declared: int,
) -> int:
    """Default deterministic rollout policy; realism is not yet validated."""
    return max(
        _production_discard_analysis(hand17, melds_declared),
        key=lambda item: (
            sum(remaining[draw] for draw in item[1]),
            -item[0],
        ),
    )[0]


def _copy_view_player(view: OpponentView | None) -> Player:
    from .selfplay import Player

    if view is None:
        return Player("attack")
    return Player(
        "attack",
        river=list(view.river),
        melds=list(view.melds),
        declared_at=view.declared_at,
        dealer_streak=view.dealer_streak if view.is_dealer else 0,
    )


def _production_seats(
    views: tuple[OpponentView, ...],
    context_template: WinContext | WinValueContext | None,
) -> tuple[int, tuple[OpponentView | None, ...], int]:
    context, _, _ = _template(context_template)
    acting_seat = 0 if context.dealer else 1
    seats: list[OpponentView | None] = [None] * 4
    remaining_seats = [seat for seat in range(4) if seat != acting_seat]
    dealer_view = next((view for view in views if view.is_dealer), None)
    if acting_seat != 0 and dealer_view is not None:
        seats[0] = dealer_view
        remaining_seats.remove(0)
    for view in views:
        if view is dealer_view and acting_seat != 0:
            continue
        if not remaining_seats:
            raise ValueError("ev_rank accepts at most three opponents")
        seats[remaining_seats.pop(0)] = view
    dealer_streak = (
        context.dealer_streak
        if acting_seat == 0
        else next(
            (view.dealer_streak for view in views if view.is_dealer),
            0,
        )
    )
    return acting_seat, tuple(seats), dealer_streak


def _draw_pool_tiles(
    remaining: list[int],
    count: int,
    rng: random.Random,
) -> list[int]:
    """Draw tile counts uniformly without replacement from one shared pool."""
    hand = [0] * 34
    total = sum(remaining)
    for _ in range(count):
        choice = rng.randrange(total)
        for tile, available in enumerate(remaining):
            if choice < available:
                remaining[tile] -= 1
                hand[tile] += 1
                total -= 1
                break
            choice -= available
    return hand


def _construct_tenpai_hand(
    remaining: list[int],
    concealed: int,
    melds_declared: int,
    rng: random.Random,
) -> list[int] | None:
    """Build a legal standard tenpai hand without repeated shanten searches."""
    melds_needed = 5 - melds_declared
    if melds_needed < 0 or concealed != 16 - 3 * melds_declared:
        return None
    available = remaining.copy()
    completed = [0] * 34
    failed: set[tuple[tuple[int, ...], int]] = set()

    def add_melds(left: int) -> bool:
        if left == 0:
            return True
        state = (tuple(available), left)
        if state in failed:
            return False
        melds = [
            (tile, tile, tile)
            for tile, count in enumerate(available)
            if count >= 3
        ]
        melds.extend(
            (tile, tile + 1, tile + 2)
            for tile in range(27)
            if tile % 9 <= 6
            and available[tile]
            and available[tile + 1]
            and available[tile + 2]
        )
        rng.shuffle(melds)
        for meld in melds:
            for tile in meld:
                available[tile] -= 1
                completed[tile] += 1
            if add_melds(left - 1):
                return True
            for tile in meld:
                available[tile] += 1
                completed[tile] -= 1
        failed.add(state)
        return False

    pairs = [tile for tile, count in enumerate(available) if count >= 2]
    rng.shuffle(pairs)
    for pair in pairs:
        available[pair] -= 2
        completed[pair] += 2
        if add_melds(melds_needed):
            removed = rng.choice([
                tile for tile, count in enumerate(completed) if count
            ])
            completed[removed] -= 1
            return completed
        available[pair] += 2
        completed[pair] -= 2
    return None


def _ron_value_hand(
    hand: list[int],
    available: list[int],
    melds_declared: int,
    rng: random.Random,
) -> tuple[tuple[int, ...], int]:
    """Return one physical completion used only to value a calibrated RON.

    A sampled tenpai hand keeps its exact tiles.  A non-tenpai sample conflicts
    with the calibrated event, so redeterminize that seat from its own tiles
    plus tiles hidden from the public, conditional on tenpai.  In both cases
    the returned tile is a real wait with a publicly available copy.  Callers
    pass the same public unknown pool for every seat so valuation cannot depend
    on the order in which concealed hands happened to be sampled.
    """
    source = [
        available[tile] + hand[tile]
        for tile in range(34)
    ]
    tenpai = (
        hand.copy()
        if _production_shanten(tuple(hand), melds_declared) == 0
        else None
    )

    def physical_waits(candidate: list[int]) -> list[int]:
        waits = []
        for tile in range(34):
            if candidate[tile] >= source[tile]:
                continue
            completed = candidate.copy()
            completed[tile] += 1
            if _production_shanten(tuple(completed), melds_declared) == -1:
                waits.append(tile)
        return waits

    waits = [] if tenpai is None else physical_waits(tenpai)
    if not waits:
        tenpai = _construct_tenpai_hand(
            source,
            16 - 3 * melds_declared,
            melds_declared,
            rng,
        )
        if tenpai is None:
            raise RuntimeError("unable to determinize a calibrated RON value hand")
        waits = physical_waits(tenpai)
        if not waits:
            raise RuntimeError("calibrated RON value hand has no physical wait")
    winning_tile = rng.choice(waits)
    tenpai[winning_tile] += 1
    return tuple(tenpai), winning_tile


def _sample_production_world(
    hand: tuple[int, ...],
    seen: tuple[int, ...],
    views: tuple[OpponentView, ...],
    turns: int,
    context_template: WinContext | WinValueContext | None,
    world_seed: int,
    tenpai_quantiles: tuple[float, ...] | None = None,
    calibrated_ron_values: bool = False,
) -> _TrialWorld:
    from .selfplay import Player

    acting_seat, seat_views, dealer_streak = _production_seats(
        views, context_template,
    )
    context, actor_melds, actor_kongs = _template(context_template)
    players = [_copy_view_player(view) for view in seat_views]
    players[acting_seat] = Player(
        "attack",
        list(hand),
        melds=list(actor_melds),
        dealer_streak=dealer_streak if acting_seat == 0 else 0,
        kongs=list(actor_kongs),
    )
    remaining = [
        4 - hand[tile] - seen[tile]
        for tile in range(34)
    ]
    rng = random.Random(world_seed)
    value_rng = random.Random(f"calibrated-ron-value:{world_seed}")
    opponent_ordinal = 0
    for seat, player in enumerate(players):
        if seat == acting_seat:
            continue
        view = seat_views[seat]
        concealed = (
            view.hand_count
            if view is not None and view.hand_count > 0
            else 16 - 3 * len(player.melds)
        )
        if concealed < 0 or concealed > sum(remaining):
            raise ValueError("visible state leaves too few tiles for opponent hands")
        public_state = view if view is not None else OpponentView([], [])
        tenpai_draw = (
            rng.random()
            if tenpai_quantiles is None
            else tenpai_quantiles[opponent_ordinal]
        )
        opponent_ordinal += 1
        target_tenpai = tenpai_draw < tenpai_score(
            public_state, len(public_state.river),
        ).score
        sampled = (
            _construct_tenpai_hand(
                remaining, concealed, len(player.melds), rng,
            )
            if target_tenpai
            else None
        )
        if sampled is None:
            sampled = _draw_pool_tiles(remaining, concealed, rng)
        else:
            for tile, count in enumerate(sampled):
                remaining[tile] -= count
        player.hand[:] = sampled
    ron_value_hands = (None, None, None, None)
    if calibrated_ron_values:
        value_hands = []
        for seat, player in enumerate(players):
            source_hand = player.hand.copy()
            declared = len(player.melds) + len(player.kongs)
            if seat == acting_seat:
                # The actor enters the discard decision holding 17 tiles, but
                # _ron_value_hand's tenpai test assumes a post-discard hand of
                # 16 - 3*declared.  Feeding it 17 makes a five-meld single wait
                # read as tenpai, so it keeps all 17 tiles and then hands an
                # 18-tile winner to scoring.  Drop one to restore that size.
                #
                # Which tile does not matter: _ron_value_hand rebuilds its pool
                # as available + hand, and available is 4 - seen - hand, so the
                # hand term cancels and the pool is 4 - seen either way.  The
                # removal only feeds the tenpai test, and it is identical for
                # every candidate, so the shared world stays candidate-neutral.
                source_hand[next(
                    tile for tile, count in enumerate(source_hand) if count
                )] -= 1
            value_hands.append(_ron_value_hand(
                source_hand,
                [
                    4 - seen[tile] - source_hand[tile]
                    for tile in range(34)
                ],
                declared,
                value_rng,
            ))
        ron_value_hands = tuple(value_hands)
    pool = [
        tile
        for tile, count in enumerate(remaining)
        for _ in range(count)
    ]
    rng.shuffle(pool)
    wall = tuple(pool[:min(4 * turns, len(pool))])
    return _TrialWorld(
        tuple(players),
        wall,
        terminal_seed=rng.randrange(2**64),
        ron_value_hands=ron_value_hands,
    )


def _per_opponent_losses(
    terminals: tuple[TerminalResult, ...],
    payments: tuple[float, ...],
    acting_seat: int,
    seat_to_opponent: tuple[int | None, ...],
    opponent_count: int,
) -> tuple[float, ...]:
    """Split the loss side of the coherent payments by which seat won.

    This is a partition of the very same signed payments that produce
    ``net_ev`` — not a separately estimated risk term — so
    ``sum(...) == risk_ev`` holds exactly whenever every winning seat maps to
    a supplied opponent view.  Callers that supply fewer than three opponents
    leave phantom seats unmapped; their wins stay in ``risk_ev`` and are
    deliberately not attributed to anyone.
    """
    if not opponent_count or not terminals:
        return ()
    losses = [0.0] * opponent_count
    for terminal, payment in zip(terminals, payments):
        if payment >= 0.0:
            continue
        winners = terminal.ron_winners or (
            () if terminal.winner is None else (terminal.winner,)
        )
        mapped = [
            seat_to_opponent[seat]
            for seat in winners
            if seat != acting_seat and seat_to_opponent[seat] is not None
        ]
        if not mapped:
            continue
        # A losing terminal never has the acting seat among its winners, so the
        # whole magnitude belongs to the opponents that did win it.
        share = -payment / len(mapped)
        for index in mapped:
            losses[index] += share
    return tuple(total / len(terminals) for total in losses)


def _rollout_entry(
    discard: int,
    terminals: tuple[TerminalResult, ...],
    acting_seat: int,
    opponent_count: int = 0,
    hidden_strata: tuple[int, ...] = (),
    seat_to_opponent: tuple[int | None, ...] = (None, None, None, None),
) -> EVRankEntry:
    payments = tuple(
        float(terminal.deltas[acting_seat]) for terminal in terminals
    )
    moments = (
        ClusteredSampleMoments.from_clustered_values(payments, hidden_strata)
        if hidden_strata
        else SampleMoments.from_values(payments)
    )
    interval = moments.ci95
    low, high = (None, None) if interval is None else interval
    actor_wins = tuple(
        terminal
        for terminal in terminals
        if terminal.kind in ("self_tsumo", "self_ron")
    )
    attack_ev = sum(max(0.0, payment) for payment in payments) / moments.n
    risk_ev = sum(max(0.0, -payment) for payment in payments) / moments.n
    p_win = len(actor_wins) / moments.n
    return EVRankEntry(
        discard=discard,
        p_win=p_win,
        mean_win_value=(
            None
            if not actor_wins
            else sum(result.value_units for result in actor_wins) / len(actor_wins)
        ),
        # Diagnostics derived from these same coherent payments; net_ev itself
        # is never composed from them.
        attack_ev=attack_ev,
        opponent_losses=_per_opponent_losses(
            terminals, payments, acting_seat, seat_to_opponent, opponent_count,
        ),
        risk_ev=risk_ev,
        net_ev=moments.mean,
        survival_adjusted_p_win=p_win,
        p_draw=sum(result.kind == "draw" for result in terminals) / moments.n,
        sample_count=moments.n,
        win_count=len(actor_wins),
        value_sum=moments.total,
        value_sum_squares=moments.sum_squares,
        standard_error=moments.standard_error,
        ci95_low=low,
        ci95_high=high,
        trial_values=payments,
        trial_strata=hidden_strata,
    )


def _calibrated_ron(
    calibration: Calibration,
    acting_seat: int,
    ron_value_hands: tuple[
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
        tuple[tuple[int, ...], int] | None,
    ],
):
    from .rollout import CalibratedRonClaim
    from .selfplay import _public_counts, _view

    def claims(
        players: Sequence[Player],
        discarder: int,
        tile: int,
    ) -> tuple[CalibratedRonClaim, ...]:
        public = _public_counts(list(players))
        # Calibration rows were recorded from each discarder against every
        # other seat, with that discarder's post-discard hand as the private
        # tile blockers.  Reproduce those semantics here for every seat.  Using
        # the acting hand on opponents' turns would make the same table state
        # depend on which seat called this estimator.
        known_hand = tuple(players[discarder].hand)
        estimates = []
        for seat, player in enumerate(players):
            if seat == discarder:
                continue
            opponent = _view(player, seat)
            # Both count vectors are built inside the rollout, so the public
            # entry point's argument checks would only re-prove what this loop
            # already guarantees, once per seat per discard.
            assessment = assess_validated_danger(
                tile, opponent, public, known_hand,
            )
            probability = (
                0.0
                if (
                    opponent.declared_at is not None
                    and "declared_safe" in assessment.modifiers
                )
                else calibration.deal_in_probability(assessment.score)
            )
            can_complete = player.hand[tile] < 4
            completed = player.hand.copy()
            if can_complete:
                completed[tile] += 1
            if (
                can_complete
                and _production_shanten(
                    tuple(completed),
                    len(player.melds) + len(player.kongs),
                )
                == -1
            ):
                value_hand = (tuple(completed), tile)
            else:
                value_hand = ron_value_hands[seat]
                if value_hand is None:
                    raise RuntimeError("missing calibrated RON value hand")
            estimates.append(CalibratedRonClaim(
                seat,
                min(1.0, max(0.0, probability or 0.0)),
                winning_hand=value_hand[0],
                scoring_tile=value_hand[1],
            ))
        return tuple(estimates)

    return claims


def _production_worlds(
    hand: tuple[int, ...],
    seen: tuple[int, ...],
    views: tuple[OpponentView, ...],
    turns: int,
    context_template: WinContext | WinValueContext | None,
    base_seed: int,
    sims: int,
    calibration_active: bool,
) -> tuple[list[_TrialWorld], int, int, int, tuple[int | None, ...]]:
    """Build the shared hidden-world layer used by every production estimate.

    Returned worlds carry a bounded set of hidden-hand determinizations reused
    in balanced fashion, each with a fresh wall stream.  Every caller that
    passes the same ``base_seed`` therefore shares one CRN base.  The final
    element maps each table seat back to its index in ``views`` (``None`` for
    the acting seat and for any seat the caller did not describe).
    """
    resolved_acting, seat_views, resolved_streak = _production_seats(
        views, context_template,
    )
    seat_to_opponent = tuple(
        None
        if seat_view is None
        else next(
            (index for index, view in enumerate(views) if view is seat_view),
            None,
        )
        for seat_view in seat_views
    )
    resolved_next = (resolved_acting + 1) % 4
    rng = random.Random(base_seed)
    hidden_count = min(sims, PRODUCTION_HIDDEN_WORLD_STRATA)
    # Stratify each opponent's latent tenpai draw independently so the
    # bounded hidden-world layer represents their public-state score.
    opponent_quantiles = []
    for _ in range(3):
        quantiles = [
            (stratum + rng.random()) / hidden_count
            for stratum in range(hidden_count)
        ]
        rng.shuffle(quantiles)
        opponent_quantiles.append(quantiles)
    hidden_worlds = [
        replace(
            _sample_production_world(
                hand,
                seen,
                views,
                turns,
                context_template,
                rng.randrange(2**64),
                tuple(
                    quantiles[stratum]
                    for quantiles in opponent_quantiles
                ),
                calibration_active,
            ),
            hidden_stratum=stratum,
        )
        for stratum in range(hidden_count)
    ]
    # Balanced reuse of a bounded set of hidden-hand determinizations keeps
    # the opponent-model integration affordable and cache-friendly. Wall
    # randomness remains fresh per trial, and all candidates share both
    # layers as CRN.
    worlds = [
        replace(
            hidden_worlds[trial % len(hidden_worlds)],
            terminal_seed=rng.randrange(2**64),
        )
        for trial in range(sims)
    ]
    return (
        worlds,
        resolved_acting,
        resolved_next,
        resolved_streak,
        seat_to_opponent,
    )


def evaluate_pass(
    counts16: tuple[int, ...] | list[int],
    opponents: tuple[OpponentView, ...] | list[OpponentView],
    visible: tuple[int, ...] | list[int],
    melds_declared: int = 0,
    turns: int = 10,
    sims: int = 400,
    seed: int | None = None,
    context_template: WinContext | WinValueContext | None = None,
    calibration: Calibration | None = None,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    rules: RulesConfig = DEFAULT_RULES,
) -> EVRankEntry:
    """Value declining a call: the same terminal path with no opening discard.

    A pon/chi hands the acting seat a discard decision now; passing does not.
    Both branches must nevertheless be priced as mean signed payment, or the
    comparison between them is meaningless.  This resolves the identical
    four-seat terminals from the undisturbed hand, so ``net_ev`` is directly
    comparable with any :func:`ev_rank` entry drawn under the same seed.
    """
    if sims < 1 or turns < 0:
        raise ValueError("sims must be positive and turns non-negative")
    from .rollout import resolve_terminal

    hand = validate_counts(counts16)
    seen = validate_counts(visible)
    if any(hand[tile] + seen[tile] > 4 for tile in range(34)):
        raise ValueError("hand and visible tiles exceed four physical copies")
    views = tuple(opponents)
    base_seed = random.randrange(2**64) if seed is None else seed
    calibration_active = calibration is not None
    worlds, acting, next_seat, streak, seat_to_opponent = _production_worlds(
        hand, seen, views, turns, context_template,
        base_seed, sims, calibration_active,
    )
    terminals = [
        resolve_terminal(
            world.players,
            world.wall,
            acting,
            next_seat,
            None,
            _production_discard_policy,
            random.Random(world.terminal_seed),
            dealer_streak=streak,
            scheme=scheme,
            rules=rules,
            calibrated_ron=(
                _calibrated_ron(calibration, acting, world.ron_value_hands)
                if calibration_active
                else None
            ),
            visible=seen,
        )
        for world in worlds
    ]
    strata = tuple(
        world.hidden_stratum
        for world in worlds
        if world.hidden_stratum is not None
    )
    # A declined call has no discard; -1 marks the entry as action-less.
    return _rollout_entry(
        -1, tuple(terminals), acting, len(views), strata, seat_to_opponent,
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
    exhaustive: bool = False,
    reference_fixed_top_k: bool = False,
    discard_policy: TerminalDiscardPolicy | None = None,
    rollout_players: Sequence[Player] | None = None,
    rollout_wall: Sequence[int] | None = None,
    acting_seat: int | None = None,
    next_seat: int | None = None,
    dealer_streak: int | None = None,
    rules: RulesConfig = DEFAULT_RULES,
    _target_discard: int | None = None,
) -> list[EVRankEntry]:
    """Rank discards by mean signed actor payment from terminal rollouts.

    Every candidate sample is one call to :func:`resolve_terminal`, hence one
    coherent game with one mutually exclusive terminal. Candidates share trial
    worlds and random streams (CRN). Push candidates use ``discard_policy`` for
    every seat; the separately labeled fold entry replaces only the acting
    seat's continuation with deterministic defense. ``discard_policy`` remains
    injectable because corpus agreement with the oracle certifies rollout
    machinery only, not the realism of the default production opponent model.

    Supplying ``rollout_players`` and ``rollout_wall`` injects a fully known
    state for machinery validation. Short injected walls (up to four tiles)
    use every physical draw order before repeating, eliminating shallow-gate
    sampling error while retaining the actual payment sample for uncertainty.
    """
    if top_k < 1 or sims < 1 or turns < 0:
        raise ValueError("top_k and sims must be positive and turns non-negative")
    from .rollout import resolve_terminal

    if (rollout_players is None) != (rollout_wall is None):
        raise ValueError("rollout_players and rollout_wall must be supplied together")
    hand = validate_counts(counts17)
    seen = validate_counts(visible)
    if any(hand[tile] + seen[tile] > 4 for tile in range(34)):
        raise ValueError("hand and visible tiles exceed four physical copies")
    views = tuple(opponents)
    analyses = discard_analysis(hand, melds_declared, seen)
    target_analysis = None
    if _target_discard is not None:
        target_analysis = next(
            (
                analysis
                for analysis in analyses
                if analysis.discard == _target_discard
            ),
            None,
        )
        if target_analysis is None:
            raise ValueError("discard must be present in the acting hand")
    ranked_danger: list[tuple[object, float]] = []
    for analysis in analyses:
        post = list(hand)
        post[analysis.discard] -= 1
        max_danger = max((danger_score(analysis.discard, view, seen, tuple(post)).score for view in views), default=0.0)
        ranked_danger.append((analysis, max_danger))
    base_seed = random.randrange(2**64) if seed is None else seed
    policy = _production_discard_policy if discard_policy is None else discard_policy
    calibration_active = calibration is not None and rollout_players is None

    worlds: list[_TrialWorld] = []
    if rollout_players is not None and rollout_wall is not None:
        injected_players = tuple(rollout_players)
        if len(injected_players) != 4:
            raise ValueError("rollout_players must contain exactly four players")
        resolved_acting = 0 if acting_seat is None else acting_seat
        resolved_next = (
            (resolved_acting + 1) % 4 if next_seat is None else next_seat
        )
        resolved_streak = 0 if dealer_streak is None else dealer_streak
        # Injected states are seat-addressed machinery fixtures with no caller
        # opponent views, so no seat maps to a per-opponent loss slot.
        seat_to_opponent = (None, None, None, None)
        wall = tuple(rollout_wall)
        orders = (
            tuple(permutations(wall))
            if len(wall) <= 4
            else ()
        )
        if orders:
            offset = base_seed % len(orders)
            for trial in range(sims):
                worlds.append(_TrialWorld(
                    injected_players,
                    wall,
                    wall_order=orders[(offset + trial) % len(orders)],
                ))
        else:
            rng = random.Random(base_seed)
            worlds = [
                _TrialWorld(
                    injected_players,
                    wall,
                    terminal_seed=rng.randrange(2**64),
                )
                for _ in range(sims)
            ]
    else:
        (
            worlds,
            resolved_acting,
            resolved_next,
            resolved_streak,
            seat_to_opponent,
        ) = _production_worlds(
            hand, seen, views, turns, context_template,
            base_seed, sims, calibration_active,
        )

    # Push and fold are different continuation policies.  Keep their terminal
    # samples separate even when they share the same opening discard.
    terminal_cache: dict[tuple[str, int], list[TerminalResult]] = {}
    def evaluate(
        analysis,
        budget: int,
        *,
        policy_key: str = "push",
        acting_discard_policy: ContinuationDiscardPolicy | None = None,
    ) -> EVRankEntry:
        terminals = terminal_cache.setdefault(
            (policy_key, analysis.discard), [],
        )
        for world in worlds[len(terminals):budget]:
            calibrated_ron = (
                _calibrated_ron(
                    calibration,
                    resolved_acting,
                    world.ron_value_hands,
                )
                if calibration_active
                else None
            )
            terminal_rng = (
                _OrderedWallRandom(world.wall, world.wall_order)
                if world.wall_order is not None
                else random.Random(world.terminal_seed)
            )
            terminals.append(resolve_terminal(
                world.players,
                world.wall,
                resolved_acting,
                resolved_next,
                analysis.discard,
                policy,
                terminal_rng,
                dealer_streak=resolved_streak,
                scheme=scheme,
                rules=rules,
                calibrated_ron=calibrated_ron,
                acting_discard_policy=acting_discard_policy,
                visible=seen,
            ))
        hidden_strata = tuple(
            world.hidden_stratum
            for world in worlds[:budget]
            if world.hidden_stratum is not None
        )
        return _rollout_entry(
            analysis.discard,
            tuple(terminals[:budget]),
            resolved_acting,
            len(views),
            hidden_strata,
            seat_to_opponent,
        )

    if target_analysis is not None:
        return [evaluate(target_analysis, sims)]

    fold_discard = _fold_choice(hand, seen, views, calibration, scheme)
    if exhaustive:
        entries = [evaluate(analysis, sims) for analysis, _ in ranked_danger]
    elif reference_fixed_top_k:
        # Legacy benchmark selector retained only for historical attribution.
        entries = [
            evaluate(analysis, sims)
            for analysis, _ in ranked_danger[:top_k + 2]
        ]
    else:
        pilot_sims = min(sims, 24)
        pilots = [
            (analysis, evaluate(analysis, pilot_sims))
            for analysis, _ in ranked_danger
        ]

        def radius(entry: EVRankEntry) -> float:
            floor = 0.50 / max(1.0, pilot_sims ** 0.5)
            return 1.959963984540054 * max(
                entry.standard_error or 0.0, floor,
            )

        best_lower = max(entry.net_ev - radius(entry) for _, entry in pilots)
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
        else:
            screened = sorted(
                screened,
                key=lambda item: (-item[1].net_ev, item[1].discard),
            )[:top_k]
        if all(
            analysis.discard != fold_discard
            for analysis, _ in screened
        ):
            screened.append(next(
                item
                for item in pilots
                if item[0].discard == fold_discard
            ))
        entries = (
            [entry for _, entry in screened]
            if pilot_sims == sims
            else [evaluate(analysis, sims) for analysis, _ in screened]
        )

    fold_analysis = next(
        analysis
        for analysis, _ in ranked_danger
        if analysis.discard == fold_discard
    )
    fold_entry = evaluate(
        fold_analysis,
        sims,
        policy_key="fold",
        acting_discard_policy=_fold_policy(views, calibration, scheme),
    )
    safe_inventory = tuple(
        tile for tile, count in enumerate(hand) if count
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
    entries.append(replace(
        fold_entry,
        is_fold=True,
        label="defense_policy",
        action_plan=FoldActionPlan(
            fold_discard,
            safe_inventory,
            (
                "defensive_continuation_each_turn",
                "genbutsu_first",
                "minimum_conditional_loss_each_turn",
                "preserve_safe_inventory",
            ),
        ),
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
) -> EVRankEntry:
    """Return one candidate from the same coherent terminal path as ev_rank."""
    ranked = ev_rank(
        counts17,
        opponents,
        visible,
        melds_declared,
        turns,
        sims,
        seed,
        context_template,
        calibration,
        top_k=34,
        scheme=scheme,
        exhaustive=True,
        _target_discard=discard,
    )
    return ranked[0]


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
