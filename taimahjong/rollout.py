"""Single-trial terminal rollouts with coherent four-seat settlement."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Sequence

from .config import DEFAULT_RULES, RulesConfig, resolve_ron_claims
from .danger import RiverEntry
from .scoring import DEFAULT_SCHEME, ScoringScheme
from .selfplay import (
    Player,
    _cached_shanten,
    _declared,
    _settle_ron_winners,
    _settlement,
)
from .tiles import validate_counts


DiscardPolicy = Callable[[tuple[int, ...], tuple[int, ...], int], int]
ContinuationDiscardPolicy = Callable[
    [tuple[int, ...], tuple[int, ...], tuple[int, ...], int],
    int,
]
PaymentDeltas = tuple[int, int, int, int]
OUTCOME_KINDS = frozenset({
    "self_tsumo",
    "self_ron",
    "opponent_ron",
    "opponent_tsumo",
    "draw",
})


@dataclass(frozen=True)
class CalibratedRonClaim:
    """RON probability plus either legacy value or a physically scored hand.

    A callback may claim for the acting seat as well as its opponents.  That is
    required when probabilities are marginal over concealed hand state: making
    only the acting seat prove a physical completion would bias the channel by
    caller identity.
    """

    seat: int
    probability: float
    value_units: int | None = None
    winning_hand: tuple[int, ...] | None = None
    scoring_tile: int | None = None

    def __post_init__(self) -> None:
        if self.seat not in range(4):
            raise ValueError("calibrated RON seat must be 0-3")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("calibrated RON probability must be between 0 and 1")
        if self.value_units is not None and self.value_units < 0:
            raise ValueError("calibrated RON value must be non-negative")
        if (self.winning_hand is None) != (self.scoring_tile is None):
            raise ValueError("calibrated RON hand and scoring tile must be supplied together")
        if (self.value_units is None) == (self.winning_hand is None):
            raise ValueError("calibrated RON requires exactly one value source")


CalibratedRon = Callable[
    [Sequence[Player], int, int],
    tuple[CalibratedRonClaim, ...],
]


@dataclass(frozen=True)
class TerminalResult:
    """One mutually exclusive terminal and its zero-sum seat payments."""

    kind: str
    winner: int | None
    discarder: int | None
    winning_tile: int | None
    deltas: PaymentDeltas
    value_units: int
    ron_winners: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        assert sum(self.kind == candidate for candidate in OUTCOME_KINDS) == 1
        assert len(self.deltas) == 4
        assert sum(self.deltas) == 0


def _copy_players(players: Sequence[Player]) -> list[Player]:
    if len(players) != 4:
        raise ValueError("terminal rollout requires exactly four players")
    return [
        Player(
            player.policy,
            list(player.hand),
            list(player.river),
            list(player.melds),
            player.declared_at,
            player.discards,
            player.dealer_streak,
            list(player.kongs),
        )
        for player in players
    ]


def _ron_claims(
    players: list[Player],
    discarder: int,
    tile: int,
    rules: RulesConfig,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    winning_hands: dict[int, tuple[int, ...]] = {}

    def can_win(seat: int) -> bool:
        hand = players[seat].hand
        if hand[tile] >= 4:
            return False
        completed = hand.copy()
        completed[tile] += 1
        winning = tuple(completed)
        if _cached_shanten(winning, _declared(players[seat])) == -1:
            winning_hands[seat] = winning
            return True
        return False

    winners = resolve_ron_claims(discarder, can_win, rules)
    return tuple((winner, winning_hands[winner]) for winner in winners)


def _terminal(
    kind: str,
    winner: int | None,
    discarder: int | None,
    winning_tile: int | None,
    deltas: PaymentDeltas,
    value_units: int,
    ron_winners: tuple[int, ...] = (),
) -> TerminalResult:
    return TerminalResult(
        kind,
        winner,
        discarder,
        winning_tile,
        deltas,
        value_units,
        ron_winners,
    )


def _ron_terminal(
    players: list[Player],
    claims: tuple[tuple[int, tuple[int, ...]], ...],
    discarder: int,
    winning_tile: int,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
) -> TerminalResult:
    winners = tuple(winner for winner, _ in claims)
    winning_hands = dict(claims)
    deltas, values = _settle_ron_winners(
        winners,
        discarder,
        players,
        winning_hands,
        winning_tile,
        dealer_streak,
        scheme,
    )
    return _terminal(
        "self_ron" if acting_seat in winners else "opponent_ron",
        winners[0],
        discarder,
        winning_tile,
        deltas,
        sum(values),
        winners,
    )


def _resolved_ron_terminal(
    players: list[Player],
    discarder: int,
    winning_tile: int,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
    rules: RulesConfig,
    calibrated_ron: CalibratedRon,
    rng: Random,
) -> TerminalResult | None:
    physical_actor_claim = False
    if discarder != acting_seat:
        hand = players[acting_seat].hand
        if hand[winning_tile] < 4:
            completed = hand.copy()
            completed[winning_tile] += 1
            physical_actor_claim = (
                _cached_shanten(
                    tuple(completed), _declared(players[acting_seat]),
                )
                == -1
            )
    estimates = {
        claim.seat: claim
        for claim in calibrated_ron(players, discarder, winning_tile)
    }
    if discarder in estimates:
        raise ValueError("calibrated RON claims must exclude the discarder")
    sampled = {
        seat
        for seat, claim in sorted(estimates.items())
        if rng.random() < claim.probability
    }
    winners = resolve_ron_claims(
        discarder,
        lambda seat: (
            (
                seat in sampled
                if seat in estimates
                else physical_actor_claim
            )
            if seat == acting_seat
            else seat in sampled
        ),
        rules,
    )
    if not winners:
        return None

    deltas = [0, 0, 0, 0]
    values: list[int] = []
    for winner in winners:
        if winner == acting_seat and winner not in estimates:
            completed = players[winner].hand.copy()
            completed[winning_tile] += 1
            payment, value = _settlement(
                "ron",
                winner,
                discarder,
                players,
                tuple(completed),
                winning_tile,
                dealer_streak,
                scheme,
            )
            deltas = [total + delta for total, delta in zip(deltas, payment)]
        else:
            claim = estimates[winner]
            if claim.winning_hand is not None:
                payment, value = _settlement(
                    "ron",
                    winner,
                    discarder,
                    players,
                    claim.winning_hand,
                    claim.scoring_tile,
                    dealer_streak,
                    scheme,
                )
                deltas = [
                    total + delta
                    for total, delta in zip(deltas, payment)
                ]
            else:
                assert claim.value_units is not None
                value = claim.value_units
                deltas[winner] += value
                deltas[discarder] -= value
        values.append(value)
    return _terminal(
        "self_ron" if acting_seat in winners else "opponent_ron",
        winners[0],
        discarder,
        winning_tile,
        tuple(deltas),
        sum(values),
        winners,
    )


def resolve_terminal(
    players: Sequence[Player],
    wall: Sequence[int],
    acting_seat: int,
    next_seat: int,
    discard: int | None,
    discard_policy: DiscardPolicy,
    rng: Random,
    *,
    dealer_streak: int = 0,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    rules: RulesConfig = DEFAULT_RULES,
    calibrated_ron: CalibratedRon | None = None,
    acting_discard_policy: ContinuationDiscardPolicy | None = None,
    visible: Sequence[int] | None = None,
) -> TerminalResult:
    """Sample one wall order and return its one coherent terminal payment.

    An acting-seat continuation starts from the caller's validated public
    counts, then adds the opening discard and every surviving rollout discard
    exactly once.  It never reconstructs visibility from rollout players,
    whose river/meld representation may retain a called tile in both places.

    ``discard`` is ``None`` for the declined-call branch: the acting seat holds
    a hand that owes no discard this turn, so play resumes at ``next_seat``
    without an opening discard.  Every later turn is unchanged, which is what
    puts a pass on the same signed-payment scale as a call.
    """
    if acting_seat not in range(4) or next_seat not in range(4):
        raise ValueError("acting and next seats must be 0-3")
    if discard is not None and discard not in range(34):
        raise ValueError("discard must be a tile index from 0 through 33")
    if acting_discard_policy is not None and visible is None:
        raise ValueError("acting discard policy requires visible tile counts")
    running_visible = (
        list(validate_counts(visible))
        if acting_discard_policy is not None and visible is not None
        else None
    )
    trial_players = _copy_players(players)
    if discard is not None:
        if not trial_players[acting_seat].hand[discard]:
            raise ValueError("discard must be present in the acting hand")

        trial_players[acting_seat].hand[discard] -= 1
        if calibrated_ron is not None:
            immediate_terminal = _resolved_ron_terminal(
                trial_players,
                acting_seat,
                discard,
                acting_seat,
                dealer_streak,
                scheme,
                rules,
                calibrated_ron,
                rng,
            )
            if immediate_terminal is not None:
                return immediate_terminal
            trial_players[acting_seat].river.append(RiverEntry(discard))
            trial_players[acting_seat].discards += 1
        else:
            immediate = _ron_claims(
                trial_players, acting_seat, discard, rules,
            )
            if immediate:
                return _ron_terminal(
                    trial_players,
                    immediate,
                    acting_seat,
                    discard,
                    acting_seat,
                    dealer_streak,
                    scheme,
                )
            if acting_discard_policy is not None:
                trial_players[acting_seat].river.append(RiverEntry(discard))
                trial_players[acting_seat].discards += 1
        if running_visible is not None:
            running_visible[discard] += 1

    remaining = [0] * 34
    for tile in wall:
        if tile not in range(34):
            raise ValueError("wall tiles must be indices from 0 through 33")
        remaining[tile] += 1

    current = next_seat
    while sum(remaining):
        draw_index = rng.randrange(sum(remaining))
        cumulative = 0
        for tile, copies in enumerate(remaining):
            cumulative += copies
            if draw_index < cumulative:
                break
        remaining[tile] -= 1
        player = trial_players[current]
        player.hand[tile] += 1

        winning_hand = tuple(player.hand)
        if _cached_shanten(winning_hand, _declared(player)) == -1:
            deltas, value = _settlement(
                "tsumo",
                current,
                None,
                trial_players,
                winning_hand,
                tile,
                dealer_streak,
                scheme,
            )
            return _terminal(
                "self_tsumo" if current == acting_seat else "opponent_tsumo",
                current,
                None,
                tile,
                deltas,
                value,
            )

        discarded = (
            acting_discard_policy(
                tuple(player.hand),
                tuple(remaining),
                tuple(running_visible),
                _declared(player),
            )
            if current == acting_seat and acting_discard_policy is not None
            else discard_policy(
                tuple(player.hand), tuple(remaining), _declared(player),
            )
        )
        if discarded not in range(34) or not player.hand[discarded]:
            raise ValueError("discard policy returned a tile absent from the hand")
        player.hand[discarded] -= 1
        if calibrated_ron is not None:
            ron_terminal = _resolved_ron_terminal(
                trial_players,
                current,
                discarded,
                acting_seat,
                dealer_streak,
                scheme,
                rules,
                calibrated_ron,
                rng,
            )
            if ron_terminal is not None:
                return ron_terminal
            origin = "tsumogiri" if discarded == tile else "tedashi"
            player.river.append(RiverEntry(discarded, origin))
            player.discards += 1
        else:
            claims = _ron_claims(
                trial_players, current, discarded, rules,
            )
            if claims:
                return _ron_terminal(
                    trial_players,
                    claims,
                    current,
                    discarded,
                    acting_seat,
                    dealer_streak,
                    scheme,
                )
            if acting_discard_policy is not None:
                origin = "tsumogiri" if discarded == tile else "tedashi"
                player.river.append(RiverEntry(discarded, origin))
                player.discards += 1
        if running_visible is not None:
            running_visible[discarded] += 1
        current = (current + 1) % 4

    return _terminal("draw", None, None, None, (0, 0, 0, 0), 0)
