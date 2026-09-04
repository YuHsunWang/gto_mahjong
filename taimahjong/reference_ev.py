"""Opt-in exact shallow-endgame outcome/payment oracle for EV measurement.

This module is deliberately separate from :mod:`taimahjong.ev`.  It knows all
four concealed hands and a short live-wall multiset, exhaustively branches on
every physical draw order, and applies one deterministic discard policy.  It is
an oracle for reference tests and corpus measurements, not a production model.
The acceptance corpus is limited to walls of at most four tiles.  Passing its
gate is necessary but not sufficient and does not certify mid-game EV, where
production ``ev_rank`` can evaluate as many as 24 turns. The comparison injects
the oracle's discard policy, so it certifies terminal classification,
settlement, and aggregation machinery—not the realism of the separate,
unvalidated production opponent model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations
from math import ceil, sqrt

from .config import DEFAULT_RULES, RulesConfig, resolve_ron_claims
from .danger import OpponentView
from .ev import ev_rank
from .scoring import (
    DEFAULT_SCHEME,
    SCHEME_3_1,
    SCHEME_5_2,
    ScoringScheme,
    WinContext,
)
from .selfplay import Player, _settle_ron_winners, _settlement
from .shanten import shanten
from .tiles import parse_tiles, validate_counts


OUTCOME_KINDS = frozenset({
    "self_tsumo",
    "self_ron",
    "opponent_ron",
    "opponent_tsumo",
    "draw",
})


@dataclass(frozen=True)
class ReferencePlayer:
    hand: tuple[int, ...]
    declared_at: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand", validate_counts(self.hand))
        if sum(self.hand) not in (16, 17):
            raise ValueError("reference concealed hands must contain 16 or 17 tiles")


@dataclass(frozen=True)
class ReferenceState:
    players: tuple[ReferencePlayer, ReferencePlayer, ReferencePlayer, ReferencePlayer]
    wall: tuple[int, ...]
    acting_seat: int = 0
    next_seat: int = 1
    dealer_streak: int = 0
    scheme: ScoringScheme = DEFAULT_SCHEME

    def __post_init__(self) -> None:
        if not 0 <= self.acting_seat < 4 or not 0 <= self.next_seat < 4:
            raise ValueError("reference seats must be 0 through 3")
        for tile in self.wall:
            if not 0 <= tile < 34:
                raise ValueError("wall tiles must be indices from 0 through 33")
        totals = [0] * 34
        for player in self.players:
            for tile, count in enumerate(player.hand):
                totals[tile] += count
        for tile in self.wall:
            totals[tile] += 1
        if any(count > 4 for count in totals):
            raise ValueError("reference state exceeds four physical copies")
        if sum(self.players[self.acting_seat].hand) != 17:
            raise ValueError("acting player must have a 17-tile post-draw hand")
        if any(
            sum(player.hand) != 16
            for seat, player in enumerate(self.players)
            if seat != self.acting_seat
        ):
            raise ValueError("non-acting players must have 16-tile hands")

    @property
    def legal_discards(self) -> tuple[int, ...]:
        return tuple(
            tile
            for tile, count in enumerate(self.players[self.acting_seat].hand)
            if count
        )


@dataclass(frozen=True)
class ReferencePayment:
    deltas: tuple[int, int, int, int]
    value_units: int


@dataclass(frozen=True)
class ReferenceOutcome:
    kind: str
    winner: int | None
    discarder: int | None
    winning_tile: int | None
    payment: ReferencePayment
    ron_winners: tuple[int, ...] = ()


@dataclass(frozen=True)
class OutcomeProbability:
    outcome: ReferenceOutcome
    probability: Fraction


@dataclass(frozen=True)
class ExactEvaluation:
    discard: int
    outcomes: tuple[OutcomeProbability, ...]
    actor_ev: Fraction


@dataclass(frozen=True)
class ReferenceCase:
    name: str
    state: ReferenceState
    seed: int
    strata: ReferenceStrata | None = None


@dataclass(frozen=True)
class ReferenceStrata:
    actor_role: str
    dealer_streak: int
    scheme: str
    wall_depth: str
    hand_state: str
    threat_level: str
    branch_character: str


@dataclass(frozen=True)
class ReferenceCaseComparison:
    name: str
    candidate_comparisons: int
    mean_absolute_ev_error: float
    exact_top_discard: int
    approximate_top_discard: int
    top1_agreement: bool
    top1_regret: float
    ranking_pairs: int
    ranking_inversion_rate: float
    rank_correlation: float  # Kendall tau-b over this case's full ordering


@dataclass(frozen=True)
class ReferenceComparison:
    cases: int
    candidate_comparisons: int
    mean_absolute_ev_error: float
    top1_agreement: float
    ranking_pairs: int
    ranking_inversion_rate: float
    mean_top1_regret: float
    max_top1_regret: float
    rank_correlation: float  # pooled Kendall tau-b over all case orderings
    case_results: tuple[ReferenceCaseComparison, ...]


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]


MIN_GATE_CASES = 26
MAX_MEAN_ABSOLUTE_EV_ERROR = 1.0
MIN_TOP1_AGREEMENT = 0.90
MAX_RANKING_INVERSION_RATE = 0.05
MAX_MEAN_TOP1_REGRET = 0.25
MAX_TOP1_REGRET = 1.0
MIN_RANK_CORRELATION = 0.90


def _players_for_settlement(state: ReferenceState) -> list[Player]:
    players = [Player("attack") for _ in range(4)]
    for seat, reference in enumerate(state.players):
        players[seat].declared_at = reference.declared_at
    return players


def _winning_hand(hand: tuple[int, ...], tile: int) -> tuple[int, ...]:
    completed = list(hand)
    completed[tile] += 1
    result = tuple(completed)
    if shanten(result) != -1:
        raise ValueError("terminal tile does not complete the winner's hand")
    return result


def _first_wait(hand: tuple[int, ...]) -> int:
    for tile in range(34):
        if hand[tile] >= 4:
            continue
        completed = list(hand)
        completed[tile] += 1
        if shanten(tuple(completed)) == -1:
            return tile
    raise ValueError("reference winner has no legal completion tile")


def _terminal_base_hand(hand: tuple[int, ...]) -> tuple[int, ...]:
    if sum(hand) == 16:
        return hand
    for tile, count in enumerate(hand):
        if not count:
            continue
        reduced = list(hand)
        reduced[tile] -= 1
        candidate = tuple(reduced)
        if shanten(candidate) == 0:
            return candidate
    raise ValueError("17-tile reference hand has no tenpai discard")


def terminal_payment(
    state: ReferenceState,
    kind: str,
    winner: int | None,
    discarder: int | None,
    scheme: ScoringScheme | None = None,
    *,
    winning_hand: tuple[int, ...] | None = None,
    winning_tile: int | None = None,
) -> ReferencePayment:
    """Apply the written outcome contract through the shared house settlement."""
    if kind not in OUTCOME_KINDS:
        raise ValueError(f"unknown reference outcome: {kind}")
    if kind == "draw":
        if winner is not None or discarder is not None:
            raise ValueError("draw has no winner or discarder")
        return ReferencePayment((0, 0, 0, 0), 0)
    if winner is None:
        raise ValueError("winning outcomes require a winner")
    is_self = winner == state.acting_seat
    if kind.startswith("self_") != is_self:
        raise ValueError("self/opponent outcome kind disagrees with winner")
    is_tsumo = kind.endswith("tsumo")
    if is_tsumo and discarder is not None:
        raise ValueError("tsumo has no discarder")
    if not is_tsumo and discarder is None:
        raise ValueError("ron requires its payment target/discarder")
    base_hand = _terminal_base_hand(state.players[winner].hand)
    if winning_tile is None:
        winning_tile = _first_wait(base_hand)
    if winning_hand is None:
        winning_hand = _winning_hand(base_hand, winning_tile)
    deltas, value = _settlement(
        "tsumo" if is_tsumo else "ron",
        winner,
        discarder,
        _players_for_settlement(state),
        winning_hand,
        winning_tile,
        state.dealer_streak,
        state.scheme if scheme is None else scheme,
    )
    return ReferencePayment(deltas, value)


def _ron_claims(
    hands: tuple[tuple[int, ...], ...],
    discarder: int,
    tile: int,
    rules: RulesConfig = DEFAULT_RULES,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    completed_hands: dict[int, tuple[int, ...]] = {}

    def can_win(seat: int) -> bool:
        if hands[seat][tile] >= 4:
            return False
        completed = list(hands[seat])
        completed[tile] += 1
        winning = tuple(completed)
        if shanten(winning) == -1:
            completed_hands[seat] = winning
            return True
        return False

    winners = resolve_ron_claims(discarder, can_win, rules)
    return tuple((winner, completed_hands[winner]) for winner in winners)


def _policy_discard(
    hand17: tuple[int, ...],
    remaining: tuple[int, ...],
    melds_declared: int = 0,
) -> int:
    assert melds_declared == 0, (
        "reference discard policy only supports states with no declared melds"
    )
    ranked: list[tuple[int, int, int]] = []
    for tile, count in enumerate(hand17):
        if not count:
            continue
        post = list(hand17)
        post[tile] -= 1
        after = tuple(post)
        after_shanten = shanten(after)
        improving = 0
        for draw, copies in enumerate(remaining):
            if not copies or after[draw] >= 4:
                continue
            advanced = list(after)
            advanced[draw] += 1
            if shanten(tuple(advanced)) < after_shanten:
                improving += copies
        ranked.append((after_shanten, -improving, tile))
    return min(ranked)[2]


def _terminal(
    state: ReferenceState,
    kind: str,
    winner: int | None,
    discarder: int | None,
    winning_tile: int | None = None,
    winning_hand: tuple[int, ...] | None = None,
    payment: ReferencePayment | None = None,
    ron_winners: tuple[int, ...] = (),
) -> ReferenceOutcome:
    return ReferenceOutcome(
        kind,
        winner,
        discarder,
        winning_tile,
        payment if payment is not None else terminal_payment(
            state, kind, winner, discarder,
            winning_hand=winning_hand, winning_tile=winning_tile,
        ),
        ron_winners,
    )


def _ron_terminal(
    state: ReferenceState,
    claims: tuple[tuple[int, tuple[int, ...]], ...],
    discarder: int,
    winning_tile: int,
) -> ReferenceOutcome:
    winners = tuple(winner for winner, _ in claims)
    winning_hands = dict(claims)
    deltas, values = _settle_ron_winners(
        winners,
        discarder,
        _players_for_settlement(state),
        winning_hands,
        winning_tile,
        state.dealer_streak,
        state.scheme,
    )
    primary = winners[0]
    return _terminal(
        state,
        "self_ron" if state.acting_seat in winners else "opponent_ron",
        primary,
        discarder,
        winning_tile,
        winning_hands[primary],
        ReferencePayment(deltas, sum(values)),
        winners,
    )


def evaluate_candidate(
    state: ReferenceState,
    discard: int,
    rules: RulesConfig = DEFAULT_RULES,
) -> ExactEvaluation:
    """Exhaust every physical order of ``state.wall`` after one legal discard."""
    if discard not in state.legal_discards:
        raise ValueError("reference discard must be present in the acting hand")
    hands = [player.hand for player in state.players]
    actor = list(hands[state.acting_seat])
    actor[discard] -= 1
    hands[state.acting_seat] = tuple(actor)
    frozen_hands = tuple(hands)
    immediate = _ron_claims(
        frozen_hands, state.acting_seat, discard, rules,
    )
    if immediate:
        outcome = _ron_terminal(
            state, immediate, state.acting_seat, discard,
        )
        return ExactEvaluation(
            discard,
            (OutcomeProbability(outcome, Fraction(1)),),
            Fraction(outcome.payment.deltas[state.acting_seat]),
        )

    wall_counts = [0] * 34
    for tile in state.wall:
        wall_counts[tile] += 1
    masses: dict[ReferenceOutcome, Fraction] = {}

    def add(outcome: ReferenceOutcome, probability: Fraction) -> None:
        masses[outcome] = masses.get(outcome, Fraction(0)) + probability

    def branch(
        current_hands: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        seat: int,
        probability: Fraction,
    ) -> None:
        total = sum(remaining)
        if not total:
            add(_terminal(state, "draw", None, None), probability)
            return
        for tile, copies in enumerate(remaining):
            if not copies:
                continue
            next_probability = probability * Fraction(copies, total)
            next_remaining = list(remaining)
            next_remaining[tile] -= 1
            drawn = list(current_hands[seat])
            drawn[tile] += 1
            drawn_hand = tuple(drawn)
            if shanten(drawn_hand) == -1:
                add(_terminal(
                    state,
                    "self_tsumo" if seat == state.acting_seat else "opponent_tsumo",
                    seat,
                    None,
                    tile,
                    drawn_hand,
                ), next_probability)
                continue
            discard_tile = (
                tile
                if state.players[seat].declared_at is not None
                else _policy_discard(drawn_hand, tuple(next_remaining))
            )
            post = list(drawn_hand)
            post[discard_tile] -= 1
            after = tuple(post)
            progressed = list(current_hands)
            progressed[seat] = after
            frozen = tuple(progressed)
            ron = _ron_claims(
                frozen, seat, discard_tile, rules,
            )
            if ron:
                add(
                    _ron_terminal(state, ron, seat, discard_tile),
                    next_probability,
                )
            else:
                branch(
                    frozen,
                    tuple(next_remaining),
                    (seat + 1) % 4,
                    next_probability,
                )

    branch(frozen_hands, tuple(wall_counts), state.next_seat, Fraction(1))
    outcomes = tuple(
        OutcomeProbability(outcome, probability)
        for outcome, probability in sorted(
            masses.items(),
            key=lambda item: (
                item[0].kind,
                -1 if item[0].winner is None else item[0].winner,
                -1 if item[0].discarder is None else item[0].discarder,
                -1 if item[0].winning_tile is None else item[0].winning_tile,
            ),
        )
    )
    actor_ev = sum(
        item.probability * item.outcome.payment.deltas[state.acting_seat]
        for item in outcomes
    )
    return ExactEvaluation(discard, outcomes, actor_ev)


def standard_small_wall_state(
    scheme: ScoringScheme = DEFAULT_SCHEME,
    wall: tuple[int, ...] = (30, 31, 32, 33),
) -> ReferenceState:
    """A valid four-hand fixture with distinct waits and a four-tile wall."""
    base = "123456m123p123s"
    players = (
        ReferencePlayer(parse_tiles(base + "111z5z")),
        ReferencePlayer(parse_tiles(base + "222z6z")),
        ReferencePlayer(parse_tiles(base + "333z7z")),
        ReferencePlayer(parse_tiles(base + "444z1z")),
    )
    actor = list(players[0].hand)
    actor[32] += 1  # post-draw 6z; legal discard and seat 1's ron tile
    return ReferenceState(
        (replace(players[0], hand=tuple(actor)), *players[1:]),
        wall,
        scheme=scheme,
    )


_ACTOR_HANDS = {
    "tenpai": "123456m123p123s111z5z",
    "1-shanten": "234568m123p123s111z5z",
    "2-shanten": "34569m1234p123s111z5z",
}
_STANDARD_OPPONENT_HANDS = (
    "123456m123p123s222z6z",
    "123456m123p123s333z7z",
    "123456m123p123s444z1z",
)
_SAFE_WALL = (6, 13, 21, 25)
_DEPTH_NAMES = {
    1: "shallow-1",
    2: "short-2",
    3: "medium-3",
    4: "deep-4",
}


def _players_with_actor(
    actor_hand: tuple[int, ...],
    opponent_hands: tuple[str, str, str],
    acting_seat: int,
    declared_opponents: int,
) -> tuple[ReferencePlayer, ReferencePlayer, ReferencePlayer, ReferencePlayer]:
    if not 0 <= declared_opponents <= 3:
        raise ValueError("declared_opponents must be from 0 through 3")
    opponents = iter(opponent_hands)
    threat_seats = {
        (acting_seat + offset) % 4
        for offset in range(1, declared_opponents + 1)
    }
    players = []
    for seat in range(4):
        if seat == acting_seat:
            players.append(ReferencePlayer(actor_hand))
        else:
            players.append(ReferencePlayer(
                parse_tiles(next(opponents)),
                declared_at=0 if seat in threat_seats else None,
            ))
    return tuple(players)  # type: ignore[return-value]


def stratified_small_wall_state(
    *,
    hand_state: str,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
    wall_depth: int,
    declared_opponents: int,
) -> ReferenceState:
    """Build the ordinary draw-dominated corpus family from named strata."""
    try:
        actor = list(parse_tiles(_ACTOR_HANDS[hand_state]))
        wall = _SAFE_WALL[:wall_depth]
    except KeyError as error:
        raise ValueError(f"unknown hand state: {hand_state}") from error
    if wall_depth not in _DEPTH_NAMES:
        raise ValueError("wall_depth must be from 1 through 4")
    actor[26] += 1  # unrelated 9s post-draw tile
    actor_hand = tuple(actor)
    if shanten(actor_hand) != {
        "tenpai": 0,
        "1-shanten": 1,
        "2-shanten": 2,
    }[hand_state]:
        raise AssertionError("actor template no longer matches its shanten stratum")
    return ReferenceState(
        _players_with_actor(
            actor_hand,
            _STANDARD_OPPONENT_HANDS,
            acting_seat,
            declared_opponents,
        ),
        wall,
        acting_seat=acting_seat,
        next_seat=(acting_seat + 1) % 4,
        dealer_streak=dealer_streak,
        scheme=scheme,
    )


_DEAL_IN_OPPONENT_HANDS = (
    "2234m111222333444z",
    "678m2234p555666777z",
    "999m678999p2234678s",
)
_DEAL_IN_COUNTS = {
    "1-shanten": (2, 3, 2, 4, 2, 4),
    "2-shanten": (1, 4, 2, 4, 2, 4),
}
_DEAL_IN_TILES = (1, 4, 10, 13, 19, 22)
_DEAL_IN_WALL = (6, 15, 21, 25)


def _deal_in_small_wall_state(
    *,
    hand_state: str,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
    wall_depth: int,
    declared_opponents: int,
) -> ReferenceState:
    """Build a state where every legal first discard deals into a wait."""
    try:
        counts = _DEAL_IN_COUNTS[hand_state]
        wall = _DEAL_IN_WALL[:wall_depth]
    except KeyError as error:
        raise ValueError(f"unsupported deal-in hand state: {hand_state}") from error
    actor = [0] * 34
    for tile, count in zip(_DEAL_IN_TILES, counts):
        actor[tile] = count
    actor_hand = tuple(actor)
    if shanten(actor_hand) != int(hand_state[0]):
        raise AssertionError("deal-in template no longer matches its shanten stratum")
    return ReferenceState(
        _players_with_actor(
            actor_hand,
            _DEAL_IN_OPPONENT_HANDS,
            acting_seat,
            declared_opponents,
        ),
        wall,
        acting_seat=acting_seat,
        next_seat=(acting_seat + 1) % 4,
        dealer_streak=dealer_streak,
        scheme=scheme,
    )


_TSUMO_OPPONENT_HANDS = (
    "3589m37p456789s1137z",
    "12368m1336p479s1124z",
    "13m1789p123446679s3z",
)


def _actor_tsumo_small_wall_state(
    *,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
) -> ReferenceState:
    """Build a four-draw state whose exact best discard self-draws surely."""
    actor = list(parse_tiles("123456789m2234p123s"))
    actor[0] += 1
    return ReferenceState(
        _players_with_actor(
            tuple(actor),
            _TSUMO_OPPONENT_HANDS,
            acting_seat,
            0,
        ),
        (10, 10, 13, 13),
        acting_seat=acting_seat,
        next_seat=(acting_seat + 1) % 4,
        dealer_streak=dealer_streak,
        scheme=scheme,
    )


def _probabilistic_small_wall_state(
    *,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
    wall: tuple[int, ...],
    declared_opponents: int,
) -> ReferenceState:
    """Build a tenpai state whose wall ordering reaches different terminals."""
    actor = list(parse_tiles(_ACTOR_HANDS["tenpai"]))
    actor[32] += 1  # post-draw 6z
    return ReferenceState(
        _players_with_actor(
            tuple(actor),
            _STANDARD_OPPONENT_HANDS,
            acting_seat,
            declared_opponents,
        ),
        wall,
        acting_seat=acting_seat,
        next_seat=(acting_seat + 1) % 4,
        dealer_streak=dealer_streak,
        scheme=scheme,
    )


@dataclass(frozen=True)
class _CorpusSpec:
    branch: str
    hand_state: str
    acting_seat: int
    dealer_streak: int
    scheme: ScoringScheme
    wall_depth: int
    threats: int
    wall: tuple[int, ...] | None = None


def _scheme_name(scheme: ScoringScheme) -> str:
    if scheme == SCHEME_3_1:
        return "3-1"
    if scheme == SCHEME_5_2:
        return "5-2"
    raise ValueError("reference corpus only supports the two house schemes")


def representative_reference_cases() -> tuple[ReferenceCase, ...]:
    """Return the auditable 26-case stratified acceptance corpus."""
    specs = (
        _CorpusSpec("draw", "tenpai", 0, 0, SCHEME_3_1, 1, 0),
        _CorpusSpec("draw", "1-shanten", 1, 0, SCHEME_5_2, 2, 1),
        _CorpusSpec("draw", "2-shanten", 0, 2, SCHEME_5_2, 3, 2),
        _CorpusSpec("draw", "tenpai", 1, 2, SCHEME_3_1, 4, 3),
        _CorpusSpec("draw", "1-shanten", 0, 0, SCHEME_3_1, 4, 2),
        _CorpusSpec("draw", "2-shanten", 1, 0, SCHEME_5_2, 1, 0),
        _CorpusSpec("deal-in", "1-shanten", 0, 0, SCHEME_3_1, 1, 1),
        _CorpusSpec("deal-in", "2-shanten", 1, 0, SCHEME_5_2, 2, 2),
        _CorpusSpec("deal-in", "1-shanten", 0, 2, SCHEME_5_2, 4, 3),
        _CorpusSpec("deal-in", "2-shanten", 1, 2, SCHEME_3_1, 3, 0),
        _CorpusSpec("deal-in", "1-shanten", 1, 0, SCHEME_3_1, 4, 1),
        _CorpusSpec("deal-in", "2-shanten", 0, 2, SCHEME_5_2, 1, 3),
        _CorpusSpec("actor-tsumo", "tenpai", 0, 0, SCHEME_3_1, 4, 0),
        _CorpusSpec("actor-tsumo", "tenpai", 1, 0, SCHEME_5_2, 4, 0),
        _CorpusSpec("actor-tsumo", "tenpai", 0, 2, SCHEME_5_2, 4, 0),
        _CorpusSpec("actor-tsumo", "tenpai", 1, 2, SCHEME_3_1, 4, 0),
        _CorpusSpec("actor-tsumo", "tenpai", 0, 0, SCHEME_5_2, 4, 0),
        _CorpusSpec("actor-tsumo", "tenpai", 1, 2, SCHEME_5_2, 4, 0),
        _CorpusSpec(
            "self-ron", "tenpai", 0, 0, SCHEME_3_1, 4, 0, (6, 6, 6, 31),
        ),
        _CorpusSpec(
            "opponent-tsumo",
            "tenpai",
            0,
            0,
            SCHEME_5_2,
            4,
            1,
            (6, 6, 32, 32),
        ),
        _CorpusSpec(
            "self-ron", "tenpai", 0, 2, SCHEME_5_2, 4, 3, (6, 6, 16, 32),
        ),
        _CorpusSpec(
            "opponent-tsumo",
            "tenpai",
            0,
            2,
            SCHEME_3_1,
            4,
            3,
            (6, 32, 32, 33),
        ),
        _CorpusSpec(
            "opponent-ron",
            "tenpai",
            1,
            0,
            SCHEME_3_1,
            4,
            0,
            (6, 6, 31, 31),
        ),
        _CorpusSpec(
            "opponent-tsumo",
            "tenpai",
            1,
            2,
            SCHEME_5_2,
            4,
            3,
            (6, 33, 33, 33),
        ),
        _CorpusSpec(
            "opponent-tsumo",
            "tenpai",
            1,
            2,
            SCHEME_3_1,
            4,
            2,
            (6, 6, 33, 33),
        ),
        _CorpusSpec(
            "self-ron", "tenpai", 1, 2, SCHEME_5_2, 4, 1, (6, 6, 6, 33),
        ),
    )
    cases = []
    for index, spec in enumerate(specs, start=1):
        if spec.branch == "draw":
            state = stratified_small_wall_state(
                hand_state=spec.hand_state,
                acting_seat=spec.acting_seat,
                dealer_streak=spec.dealer_streak,
                scheme=spec.scheme,
                wall_depth=spec.wall_depth,
                declared_opponents=spec.threats,
            )
        elif spec.branch == "deal-in":
            state = _deal_in_small_wall_state(
                hand_state=spec.hand_state,
                acting_seat=spec.acting_seat,
                dealer_streak=spec.dealer_streak,
                scheme=spec.scheme,
                wall_depth=spec.wall_depth,
                declared_opponents=spec.threats,
            )
        elif spec.branch == "actor-tsumo":
            state = _actor_tsumo_small_wall_state(
                acting_seat=spec.acting_seat,
                dealer_streak=spec.dealer_streak,
                scheme=spec.scheme,
            )
        else:
            if spec.wall is None:
                raise AssertionError("probabilistic corpus case requires a wall")
            state = _probabilistic_small_wall_state(
                acting_seat=spec.acting_seat,
                dealer_streak=spec.dealer_streak,
                scheme=spec.scheme,
                wall=spec.wall,
                declared_opponents=spec.threats,
            )
        role = "dealer" if spec.acting_seat == 0 else "nondealer"
        scheme_name = _scheme_name(spec.scheme)
        threat_level = (
            "none" if spec.threats == 0
            else "one" if spec.threats == 1
            else "multiple"
        )
        strata = ReferenceStrata(
            role,
            spec.dealer_streak,
            scheme_name,
            _DEPTH_NAMES[spec.wall_depth],
            spec.hand_state,
            threat_level,
            spec.branch,
        )
        name = (
            f"{spec.branch}-{spec.hand_state}-{role}-streak"
            f"{spec.dealer_streak}-{scheme_name}-{strata.wall_depth}-"
            f"threat-{threat_level}"
        )
        cases.append(ReferenceCase(name, state, 6100 + index, strata))
    return tuple(cases)


def compare_reference_corpus(
    cases: tuple[ReferenceCase, ...],
    *,
    sims: int = 24,
    rules: RulesConfig = DEFAULT_RULES,
    seed_offset: int = 0,
) -> ReferenceComparison:
    absolute_errors: list[float] = []
    agreements = 0
    inversions = 0
    concordances = 0
    exact_ties = 0
    approximate_ties = 0
    ranking_pairs = 0
    comparisons = 0
    regrets: list[float] = []
    case_results: list[ReferenceCaseComparison] = []
    for case in cases:
        exact = {
            discard: float(
                evaluate_candidate(case.state, discard, rules).actor_ev
            )
            for discard in case.state.legal_discards
        }
        actor_hand = case.state.players[case.state.acting_seat].hand
        opponents = []
        visible = [0] * 34
        for ordinal, seat in enumerate(
            seat for seat in range(4) if seat != case.state.acting_seat
        ):
            player = case.state.players[seat]
            river = [15 + ordinal] if player.declared_at is not None else []
            if river:
                visible[river[0]] += 1
            opponents.append(OpponentView(
                river,
                [],
                declared_at=0 if player.declared_at is not None else None,
                is_dealer=seat == 0,
                dealer_streak=case.state.dealer_streak if seat == 0 else 0,
                hand_count=16,
            ))
        approximate = {
            entry.discard: entry.net_ev
            for entry in ev_rank(
                actor_hand,
                tuple(opponents),
                tuple(visible),
                turns=max(1, ceil(len(case.state.wall) / 4)),
                sims=sims,
                seed=case.seed + seed_offset,
                context_template=WinContext(
                    winning_tile=0,
                    dealer=case.state.acting_seat == 0,
                    dealer_streak=(
                        case.state.dealer_streak
                        if case.state.acting_seat == 0
                        else 0
                    ),
                ),
                scheme=case.state.scheme,
                exhaustive=True,
                discard_policy=_policy_discard,
                rollout_players=tuple(
                    Player(
                        "attack",
                        list(reference.hand),
                        declared_at=reference.declared_at,
                    )
                    for reference in case.state.players
                ),
                rollout_wall=case.state.wall,
                acting_seat=case.state.acting_seat,
                next_seat=case.state.next_seat,
                dealer_streak=case.state.dealer_streak,
                rules=rules,
            )
            if not entry.is_fold
        }
        shared = sorted(exact.keys() & approximate.keys())
        if not shared:
            raise ValueError(f"no shared discard candidates for {case.name}")
        comparisons += len(shared)
        case_errors = [
            abs(approximate[tile] - exact[tile]) for tile in shared
        ]
        absolute_errors.extend(case_errors)
        exact_top = max(shared, key=lambda tile: (exact[tile], -tile))
        approximate_top = max(
            shared, key=lambda tile: (approximate[tile], -tile),
        )
        agreement = exact_top == approximate_top
        agreements += int(agreement)
        regret = exact[exact_top] - exact[approximate_top]
        regrets.append(regret)
        case_inversions = 0
        case_concordances = 0
        case_exact_ties = 0
        case_approximate_ties = 0
        for left, right in combinations(shared, 2):
            exact_delta = exact[left] - exact[right]
            approximate_delta = approximate[left] - approximate[right]
            if exact_delta == 0 and approximate_delta == 0:
                continue
            if exact_delta == 0:
                exact_ties += 1
                case_exact_ties += 1
                continue
            if approximate_delta == 0:
                approximate_ties += 1
                case_approximate_ties += 1
                continue
            ranking_pairs += 1
            if (exact_delta > 0) != (approximate_delta > 0):
                inversions += 1
                case_inversions += 1
            else:
                concordances += 1
                case_concordances += 1
        case_pairs = case_concordances + case_inversions
        case_denominator = sqrt(
            (case_pairs + case_exact_ties)
            * (case_pairs + case_approximate_ties)
        )
        case_results.append(ReferenceCaseComparison(
            case.name,
            len(shared),
            sum(case_errors) / len(case_errors),
            exact_top,
            approximate_top,
            agreement,
            regret,
            case_pairs,
            0.0 if not case_pairs else case_inversions / case_pairs,
            (
                0.0
                if not case_denominator
                else (case_concordances - case_inversions) / case_denominator
            ),
        ))
    correlation_denominator = sqrt(
        (ranking_pairs + exact_ties)
        * (ranking_pairs + approximate_ties)
    )
    return ReferenceComparison(
        len(cases),
        comparisons,
        0.0 if not absolute_errors else sum(absolute_errors) / len(absolute_errors),
        0.0 if not cases else agreements / len(cases),
        ranking_pairs,
        0.0 if not ranking_pairs else inversions / ranking_pairs,
        0.0 if not regrets else sum(regrets) / len(regrets),
        0.0 if not regrets else max(regrets),
        (
            0.0
            if not correlation_denominator
            else (concordances - inversions) / correlation_denominator
        ),
        tuple(case_results),
    )


def corpus_gate(comparison: ReferenceComparison) -> GateResult:
    """Apply thresholds for the shallow-endgame corpus (walls up to four).

    Passing is necessary but not sufficient: this gate does not certify
    mid-game EV, while production ``ev_rank`` supports up to 24 turns. Because
    the comparison injects the oracle's own discard policy, passage certifies
    the machinery—terminal classification, settlement, and aggregation—not
    the realism of the separate, unvalidated production opponent model.
    """
    failures = []
    checks = (
        (
            comparison.cases >= MIN_GATE_CASES,
            f"cases {comparison.cases} < {MIN_GATE_CASES}",
        ),
        (
            comparison.mean_absolute_ev_error <= MAX_MEAN_ABSOLUTE_EV_ERROR,
            "mean_absolute_ev_error "
            f"{comparison.mean_absolute_ev_error:.6f} > "
            f"{MAX_MEAN_ABSOLUTE_EV_ERROR:.6f}",
        ),
        (
            comparison.top1_agreement >= MIN_TOP1_AGREEMENT,
            f"top1_agreement {comparison.top1_agreement:.6f} < "
            f"{MIN_TOP1_AGREEMENT:.6f}",
        ),
        (
            comparison.ranking_inversion_rate
            <= MAX_RANKING_INVERSION_RATE,
            "ranking_inversion_rate "
            f"{comparison.ranking_inversion_rate:.6f} > "
            f"{MAX_RANKING_INVERSION_RATE:.6f}",
        ),
        (
            comparison.mean_top1_regret <= MAX_MEAN_TOP1_REGRET,
            f"mean_top1_regret {comparison.mean_top1_regret:.6f} > "
            f"{MAX_MEAN_TOP1_REGRET:.6f}",
        ),
        (
            comparison.max_top1_regret <= MAX_TOP1_REGRET,
            f"max_top1_regret {comparison.max_top1_regret:.6f} > "
            f"{MAX_TOP1_REGRET:.6f}",
        ),
        (
            comparison.rank_correlation >= MIN_RANK_CORRELATION,
            f"rank_correlation {comparison.rank_correlation:.6f} < "
            f"{MIN_RANK_CORRELATION:.6f}",
        ),
    )
    failures.extend(message for passed, message in checks if not passed)
    return GateResult(not failures, tuple(failures))
