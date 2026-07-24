"""Opt-in exact small-wall outcome/payment oracle for EV measurement.

This module is deliberately separate from :mod:`taimahjong.ev`.  It knows all
four concealed hands and a short live-wall multiset, exhaustively branches on
every physical draw order, and applies one deterministic discard policy.  It is
an oracle for reference tests and corpus measurements, not a production model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations
from math import ceil

from .danger import OpponentView
from .ev import ev_rank
from .scoring import DEFAULT_SCHEME, SCHEME_3_1, SCHEME_5_2, ScoringScheme
from .selfplay import Player, _settlement
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


@dataclass(frozen=True)
class ReferenceComparison:
    cases: int
    candidate_comparisons: int
    mean_absolute_ev_error: float
    top1_agreement: float
    ranking_pairs: int
    ranking_inversion_rate: float


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


def _ron_winner(
    hands: tuple[tuple[int, ...], ...],
    discarder: int,
    tile: int,
) -> tuple[int, tuple[int, ...]] | None:
    for offset in range(1, 4):
        seat = (discarder + offset) % 4
        if hands[seat][tile] >= 4:
            continue
        completed = list(hands[seat])
        completed[tile] += 1
        winning = tuple(completed)
        if shanten(winning) == -1:
            return seat, winning
    return None


def _policy_discard(
    hand17: tuple[int, ...],
    remaining: tuple[int, ...],
) -> int:
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
) -> ReferenceOutcome:
    return ReferenceOutcome(
        kind,
        winner,
        discarder,
        winning_tile,
        terminal_payment(
            state,
            kind,
            winner,
            discarder,
            winning_hand=winning_hand,
            winning_tile=winning_tile,
        ),
    )


def evaluate_candidate(state: ReferenceState, discard: int) -> ExactEvaluation:
    """Exhaust every physical order of ``state.wall`` after one legal discard."""
    if discard not in state.legal_discards:
        raise ValueError("reference discard must be present in the acting hand")
    hands = [player.hand for player in state.players]
    actor = list(hands[state.acting_seat])
    actor[discard] -= 1
    hands[state.acting_seat] = tuple(actor)
    frozen_hands = tuple(hands)
    immediate = _ron_winner(frozen_hands, state.acting_seat, discard)
    if immediate is not None:
        winner, winning = immediate
        outcome = _terminal(
            state,
            "self_ron" if winner == state.acting_seat else "opponent_ron",
            winner,
            state.acting_seat,
            discard,
            winning,
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
            discard_tile = _policy_discard(
                drawn_hand, tuple(next_remaining),
            )
            post = list(drawn_hand)
            post[discard_tile] -= 1
            after = tuple(post)
            progressed = list(current_hands)
            progressed[seat] = after
            frozen = tuple(progressed)
            ron = _ron_winner(frozen, seat, discard_tile)
            if ron is not None:
                winner, winning = ron
                add(_terminal(
                    state,
                    "self_ron" if winner == state.acting_seat else "opponent_ron",
                    winner,
                    seat,
                    discard_tile,
                    winning,
                ), next_probability)
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


def representative_reference_cases() -> tuple[ReferenceCase, ...]:
    return (
        ReferenceCase(
            "mixed-terminals-3-1",
            standard_small_wall_state(SCHEME_3_1, (30, 31, 32, 33)),
            6101,
        ),
        ReferenceCase(
            "draw-branch-5-2",
            standard_small_wall_state(SCHEME_5_2, (28, 29, 30)),
            6102,
        ),
    )


def compare_reference_corpus(
    cases: tuple[ReferenceCase, ...],
    *,
    sims: int = 24,
) -> ReferenceComparison:
    absolute_errors: list[float] = []
    agreements = 0
    inversions = 0
    ranking_pairs = 0
    comparisons = 0
    for case in cases:
        exact = {
            discard: float(evaluate_candidate(case.state, discard).actor_ev)
            for discard in case.state.legal_discards
        }
        actor_hand = case.state.players[case.state.acting_seat].hand
        approximate = {
            entry.discard: entry.net_ev
            for entry in ev_rank(
                actor_hand,
                (),
                (0,) * 34,
                turns=max(1, ceil(len(case.state.wall) / 4)),
                sims=sims,
                seed=case.seed,
                scheme=case.state.scheme,
                exhaustive=True,
            )
            if not entry.is_fold
        }
        shared = sorted(exact.keys() & approximate.keys())
        comparisons += len(shared)
        absolute_errors.extend(
            abs(approximate[tile] - exact[tile]) for tile in shared
        )
        exact_top = max(shared, key=lambda tile: (exact[tile], -tile))
        approximate_top = max(
            shared, key=lambda tile: (approximate[tile], -tile),
        )
        agreements += int(exact_top == approximate_top)
        for left, right in combinations(shared, 2):
            exact_delta = exact[left] - exact[right]
            approximate_delta = approximate[left] - approximate[right]
            if exact_delta == 0 or approximate_delta == 0:
                continue
            ranking_pairs += 1
            inversions += int((exact_delta > 0) != (approximate_delta > 0))
    return ReferenceComparison(
        len(cases),
        comparisons,
        0.0 if not absolute_errors else sum(absolute_errors) / len(absolute_errors),
        0.0 if not cases else agreements / len(cases),
        ranking_pairs,
        0.0 if not ranking_pairs else inversions / ranking_pairs,
    )
