"""Single-trial terminal rollouts with coherent four-seat settlement."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Sequence

from .config import DEFAULT_RULES, RulesConfig, resolve_ron_claims
from .scoring import DEFAULT_SCHEME, ScoringScheme
from .selfplay import (
    Player,
    _cached_shanten,
    _declared,
    _settle_ron_winners,
    _settlement,
)


DiscardPolicy = Callable[[tuple[int, ...], tuple[int, ...], int], int]
PaymentDeltas = tuple[int, int, int, int]
OUTCOME_KINDS = frozenset({
    "self_tsumo",
    "self_ron",
    "opponent_ron",
    "opponent_tsumo",
    "draw",
})


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


def resolve_terminal(
    players: Sequence[Player],
    wall: Sequence[int],
    acting_seat: int,
    next_seat: int,
    discard: int,
    discard_policy: DiscardPolicy,
    rng: Random,
    *,
    dealer_streak: int = 0,
    scheme: ScoringScheme = DEFAULT_SCHEME,
    rules: RulesConfig = DEFAULT_RULES,
) -> TerminalResult:
    """Sample one wall order and return its one coherent terminal payment."""
    if acting_seat not in range(4) or next_seat not in range(4):
        raise ValueError("acting and next seats must be 0-3")
    if discard not in range(34):
        raise ValueError("discard must be a tile index from 0 through 33")
    trial_players = _copy_players(players)
    if not trial_players[acting_seat].hand[discard]:
        raise ValueError("discard must be present in the acting hand")

    trial_players[acting_seat].hand[discard] -= 1
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

        discarded = discard_policy(
            tuple(player.hand), tuple(remaining), _declared(player),
        )
        if discarded not in range(34) or not player.hand[discarded]:
            raise ValueError("discard policy returned a tile absent from the hand")
        player.hand[discarded] -= 1
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
        current = (current + 1) % 4

    return _terminal("draw", None, None, None, (0, 0, 0, 0), 0)
