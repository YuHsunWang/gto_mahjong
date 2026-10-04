"""Single-trial terminal rollouts with coherent four-seat settlement."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from random import Random
from typing import Callable, Sequence

from .config import DEFAULT_RULES, RulesConfig, resolve_ron_claims
from .danger import KongLike, MeldLike, RiverEntry
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
MIXTURE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class CalibratedRonClaim:
    """RON probability plus either legacy value or a physically scored hand.

    Calibration prices every non-acting opponent at its marginal rate, whatever
    its sampled hand; the hand only values the ron.  The acting seat's actual
    hand decides its claim physically.
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


@dataclass(frozen=True)
class TerminalMixture:
    """The conditional terminal distribution of one sampled world.

    A trial samples the hidden hands and the wall order; it does not sample
    whether a priced RON claim fires.  Keeping those claims as probabilities
    makes the trial contribute ``E[X | H, U]`` instead of ``X`` itself, which
    by the total-variance decomposition can only lower the estimator's
    variance -- and it keeps the claim consistent with the very hands the
    trial drew, which an independent coin toss did not.

    ``outcomes`` pairs each mutually exclusive terminal with its probability
    under that fixed world.  A world with no priced claim yields exactly one
    outcome of probability one, so the uncalibrated path is unchanged.
    """

    outcomes: tuple[tuple[float, TerminalResult], ...]

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise ValueError("a terminal mixture must carry at least one outcome")
        if any(probability < 0.0 for probability, _ in self.outcomes):
            raise ValueError("terminal mixture probabilities must be non-negative")
        assert abs(self.total_probability - 1.0) <= MIXTURE_TOLERANCE

    @property
    def total_probability(self) -> float:
        return sum(probability for probability, _ in self.outcomes)

    @property
    def expected_deltas(self) -> tuple[float, float, float, float]:
        """Probability-weighted seat payments; still exactly zero-sum."""
        totals = [0.0, 0.0, 0.0, 0.0]
        for probability, terminal in self.outcomes:
            for seat, delta in enumerate(terminal.deltas):
                totals[seat] += probability * delta
        return (totals[0], totals[1], totals[2], totals[3])

    def probability(self, *kinds: str) -> float:
        """Total probability of the named outcome kinds."""
        unknown = set(kinds) - OUTCOME_KINDS
        if unknown:
            raise ValueError(f"unknown terminal kinds: {sorted(unknown)}")
        return sum(
            probability
            for probability, terminal in self.outcomes
            if terminal.kind in kinds
        )

    def expected_value_units(self, *kinds: str) -> float:
        """Probability-weighted hand value over the named kinds.

        Weighted by probability, not renormalized: dividing by
        :meth:`probability` gives the conditional mean value of those kinds.
        """
        unknown = set(kinds) - OUTCOME_KINDS
        if unknown:
            raise ValueError(f"unknown terminal kinds: {sorted(unknown)}")
        return sum(
            probability * terminal.value_units
            for probability, terminal in self.outcomes
            if terminal.kind in kinds
        )

    @property
    def sole(self) -> TerminalResult:
        """The one certain terminal, for callers that price no claim."""
        if len(self.outcomes) != 1:
            raise ValueError(
                "terminal mixture holds several outcomes; collapsing it here "
                "would reintroduce the coin toss it replaced"
            )
        probability, terminal = self.outcomes[0]
        if abs(probability - 1.0) > MIXTURE_TOLERANCE:
            raise ValueError("sole terminal must carry probability one")
        return terminal


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
    *,
    wall_remaining: int | None = None,
    rules: RulesConfig = DEFAULT_RULES,
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
        wall_remaining=wall_remaining,
        rules=rules,
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


def _calibrated_claim_probabilities(
    players: list[Player],
    discarder: int,
    winning_tile: int,
    acting_seat: int,
    calibrated_ron: CalibratedRon,
) -> tuple[dict[int, float], dict[int, CalibratedRonClaim]]:
    """Per-seat RON probabilities for one discard, plus the claims behind them.

    The acting seat is the one seat whose claim is physical rather than
    priced: the hand it actually holds decides whether it can win.  When it
    can, the house's nearest-claim priority still applies: seats between the
    discarder and the actor take their priced share first, the actor takes
    all the mass they leave, and seats after the actor never get the tile.
    """
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
    if acting_seat != discarder:
        estimates.pop(acting_seat, None)
    probabilities = {
        seat: claim.probability for seat, claim in estimates.items()
    }
    if acting_seat != discarder:
        if physical_actor_claim:
            nearer = set()
            seat = (discarder + 1) % 4
            while seat != acting_seat:
                nearer.add(seat)
                seat = (seat + 1) % 4
            probabilities = {
                seat: probability
                for seat, probability in probabilities.items()
                if seat in nearer
            }
            probabilities[acting_seat] = max(0.0, 1.0 - sum(probabilities.values()))
        else:
            probabilities[acting_seat] = 0.0
    return probabilities, estimates


def _winner_distribution(
    probabilities: dict[int, float],
    discarder: int,
    rules: RulesConfig,
) -> dict[tuple[int, ...], float]:
    """Exact distribution over RON winner sets for one discard.

    Calibration records only the actual winner, so the seat probabilities are
    already mutually exclusive and must not pass through claim arbitration a
    second time.  Independently fitted rows can sum above one; in that case
    proportional normalization preserves their relative weights and leaves a
    zero no-win residual.  Otherwise the empty tuple carries the residual mass
    with which the trial continues.
    """
    seats = tuple((discarder + offset) % 4 for offset in range(1, 4))
    total = sum(probabilities.get(seat, 0.0) for seat in seats)
    scale = 1.0 / total if total > 1.0 else 1.0
    distribution = {
        (seat,): probabilities.get(seat, 0.0) * scale
        for seat in seats
        if probabilities.get(seat, 0.0)
    }
    residual = 0.0 if total > 1.0 else 1.0 - total
    # A physical actor claim takes exactly the mass the nearer seats leave, so
    # its sum lands on one up to rounding; that dust is not a surviving world.
    if residual > MIXTURE_TOLERANCE:
        distribution[()] = residual
    return distribution


@lru_cache(maxsize=8192)
def _cached_ron_settlement(
    winner: int,
    discarder: int,
    winning_hand: tuple[int, ...],
    winning_tile: int,
    melds: tuple[MeldLike, ...],
    kongs: tuple[KongLike, ...],
    declared: bool,
    dealer_streak: int,
    scheme: ScoringScheme,
    *,
    wall_remaining: int | None = None,
    rules: RulesConfig = DEFAULT_RULES,
) -> tuple[PaymentDeltas, int]:
    """Cache settlement inputs; winner fixes seat wind, wall fixes last tile.

    A missing wall count identifies a discard without a normal live draw.
    Rules are part of the key, including the menqing self-draw option.
    """
    players = [Player("attack") for _ in range(4)]
    players[winner].melds = list(melds)
    players[winner].kongs = list(kongs)
    players[winner].declared_at = 0 if declared else None
    return _settlement(
        "ron", winner, discarder, players, winning_hand, winning_tile,
        dealer_streak, scheme, wall_remaining=wall_remaining, rules=rules,
    )


def _calibrated_ron_terminal(
    players: list[Player],
    winners: tuple[int, ...],
    estimates: dict[int, CalibratedRonClaim],
    discarder: int,
    winning_tile: int,
    acting_seat: int,
    dealer_streak: int,
    scheme: ScoringScheme,
    *,
    wall_remaining: int | None = None,
    rules: RulesConfig = DEFAULT_RULES,
) -> TerminalResult:
    """Settle one already-decided calibrated RON winner set."""
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
                wall_remaining=wall_remaining,
                rules=rules,
            )
            deltas = [total + delta for total, delta in zip(deltas, payment)]
        else:
            claim = estimates[winner]
            if claim.winning_hand is not None:
                player = players[winner]
                payment, value = _cached_ron_settlement(
                    winner,
                    discarder,
                    claim.winning_hand,
                    claim.scoring_tile,
                    tuple(player.melds),
                    tuple(player.kongs),
                    player.declared,
                    dealer_streak,
                    scheme,
                    wall_remaining=wall_remaining,
                    rules=rules,
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


def resolve_terminal_distribution(
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
    wall_remaining: int | None = None,
    opening_live_draw: bool = False,
) -> TerminalMixture:
    """Sample one wall order and return its whole terminal distribution.

    The wall order and the hidden hands come from ``rng``; the priced RON
    claims do not.  Instead the trial carries a surviving-mass weight: at every
    discard the claim distribution takes its share of that mass and the rest of
    the trial continues with what is left, so one world yields ``E[X | H, U]``
    exactly rather than one Bernoulli draw from it.  Without a priced claim the
    mass never splits and the mixture holds one certain terminal.

    An acting-seat continuation starts from the caller's validated public
    counts, then adds the opening discard and every surviving rollout discard
    exactly once.  It never reconstructs visibility from rollout players,
    whose river/meld representation may retain a called tile in both places.

    ``wall_remaining`` counts real live tiles before the rollout draws, even
    when ``wall`` is a shorter simulation horizon. ``opening_live_draw`` says
    the opening discard follows a normal live draw; calls and kong replacement
    draws must leave it false.

    ``discard`` is ``None`` for the declined-call branch: the acting seat holds
    a hand that owes no discard this turn, so play resumes at ``next_seat``
    without an opening discard.  Every later turn is unchanged, which is what
    puts a pass on the same signed-payment scale as a call.
    """
    # Count the real live wall separately from a truncated rollout horizon.
    live_remaining = len(wall) if wall_remaining is None else wall_remaining
    if (
        not isinstance(live_remaining, int)
        or isinstance(live_remaining, bool)
        or live_remaining < len(wall)
    ):
        raise ValueError("wall_remaining must be an integer at least the simulated wall size")
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
    records_river = calibrated_ron is not None or acting_discard_policy is not None
    outcomes: list[tuple[float, TerminalResult]] = []
    survival = 1.0

    def claim_ron(current: int, tile: int, wall_remaining: int | None = None) -> bool:
        """Take the RON branches of one discard; True once no mass survives."""
        nonlocal survival
        if calibrated_ron is None:
            claims = _ron_claims(trial_players, current, tile, rules)
            if not claims:
                return False
            outcomes.append((
                survival,
                _ron_terminal(
                    trial_players,
                    claims,
                    current,
                    tile,
                    acting_seat,
                    dealer_streak,
                    scheme,
                    wall_remaining=wall_remaining,
                    rules=rules,
                ),
            ))
            survival = 0.0
            return True

        probabilities, estimates = _calibrated_claim_probabilities(
            trial_players, current, tile, acting_seat, calibrated_ron,
        )
        distribution = _winner_distribution(probabilities, current, rules)
        for winners, probability in distribution.items():
            if not winners:
                continue
            outcomes.append((
                survival * probability,
                _calibrated_ron_terminal(
                    trial_players,
                    winners,
                    estimates,
                    current,
                    tile,
                    acting_seat,
                    dealer_streak,
                    scheme,
                    wall_remaining=wall_remaining,
                    rules=rules,
                ),
            ))
        survival *= distribution.get((), 0.0)
        return not survival

    if discard is not None:
        if not trial_players[acting_seat].hand[discard]:
            raise ValueError("discard must be present in the acting hand")

        trial_players[acting_seat].hand[discard] -= 1
        if claim_ron(
            acting_seat, discard,
            wall_remaining=live_remaining if opening_live_draw else None,
        ):
            return TerminalMixture(tuple(outcomes))
        if records_river:
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
        live_remaining -= 1
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
                wall_remaining=live_remaining,
                rules=rules,
            )
            outcomes.append((
                survival,
                _terminal(
                    "self_tsumo" if current == acting_seat else "opponent_tsumo",
                    current,
                    None,
                    tile,
                    deltas,
                    value,
                ),
            ))
            return TerminalMixture(tuple(outcomes))

        # A migi declaration locks the hand to tsumogiri: the declared player
        # may only discard the tile just drawn.
        discarded = (
            tile
            if player.declared
            else (
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
        )
        if discarded not in range(34) or not player.hand[discarded]:
            raise ValueError("discard policy returned a tile absent from the hand")
        player.hand[discarded] -= 1
        if claim_ron(current, discarded, wall_remaining=live_remaining):
            return TerminalMixture(tuple(outcomes))
        if records_river:
            origin = "tsumogiri" if discarded == tile else "tedashi"
            player.river.append(RiverEntry(discarded, origin))
            player.discards += 1
        if running_visible is not None:
            running_visible[discarded] += 1
        current = (current + 1) % 4

    outcomes.append((
        survival, _terminal("draw", None, None, None, (0, 0, 0, 0), 0),
    ))
    return TerminalMixture(tuple(outcomes))


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
    wall_remaining: int | None = None,
    opening_live_draw: bool = False,
) -> TerminalResult:
    """One coherent terminal payment, for worlds that leave nothing uncertain.

    Kept for fixtures and for callers whose claims are all certain.  It raises
    on a genuine mixture rather than collapsing it, because collapsing would
    reintroduce exactly the coin toss that
    :func:`resolve_terminal_distribution` removed.
    """
    return resolve_terminal_distribution(
        players,
        wall,
        acting_seat,
        next_seat,
        discard,
        discard_policy,
        rng,
        dealer_streak=dealer_streak,
        scheme=scheme,
        rules=rules,
        calibrated_ron=calibrated_ron,
        acting_discard_policy=acting_discard_policy,
        visible=visible,
        wall_remaining=wall_remaining,
        opening_live_draw=opening_live_draw,
    ).sole
