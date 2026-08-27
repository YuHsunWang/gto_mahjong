"""Empirical game over a restricted strategy set in the shallow endgame.

Step 3 of ``docs/equilibrium-plan.md`` asked for iterated best response until
convergence.  Over *unrestricted* policies that is not reachable, and for the
reason ``best_response.py`` already records: a non-acting seat decides only
after drawing, so its information sets are keyed by a hand that differs in
every sampled world and are almost surely singletons.  Only the acting seat's
opening decision is shared across worlds.

So the strategy space is restricted to a small, explicitly listed set of whole
policies, and the game is played over that set.  This is the same move a poker
solver makes when it abstracts a continuum of bet sizes down to a handful: the
equilibrium is exact *within the abstraction* and says nothing outside it.
Every claim built on this module must carry the strategy set with it.

What is exact here: given a sampled world and a profile, every physical draw
order is enumerated with :class:`~fractions.Fraction`, so each seat's payoff is
the exact expectation over draw orders.  What is sampled: the hidden hands,
drawn from production's belief model, shared across all profiles as common
random numbers so profile comparisons are paired.

Seats are held to their own information.  Each seat's policy is called with its
own belief pool -- four copies minus its own hand minus everything publicly
visible -- never with the true remaining wall, which no seat can see.

The players are *roles*, not absolute seats: the actor, then the seats drawing
1, 2 and 3 turns after it.  The actor sits at seat 0 in 13 of the 26 cases and
at seat 1 in the other 13, so a seat-indexed profile entry meant the actor in
half the corpus and a downstream seat in the other half, and the payoff row
averaged the two.  Role indexing buys no extra observations -- either way each
player gets the same 26 case clusters -- only a player that means one thing.
It also moves the remaining confound rather than removing it: the dealer is
absolute seat 0, so each role now mixes 13 dealer cases with 13 non-dealer
ones, where seat indexing had kept that clean and the role dirty.

Nothing here is worth reading without :meth:`EmpiricalGame.regret_interval`.
:meth:`EmpiricalGame.equilibria` compares point estimates, and at a thin budget
it returns whichever profile the sampling noise favoured: the same corpus named
``SESE`` at 20 worlds, ``SESS`` at 40, nothing at 60 and ``SEES`` at 400.  A
profile is only *shown* not to be an equilibrium when its interval clears zero,
and only shown to be one when the interval sits entirely below it -- which, at
every budget tried so far, no profile has managed.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from random import Random
from typing import Callable

from .config import DEFAULT_RULES, RulesConfig
from .ev import (
    _defensive_discard_policy,
    _production_discard_policy,
    _production_shanten,
)
from .reference_ev import (
    ReferenceCase,
    ReferenceState,
    _policy_discard,
    _ron_claims,
    _ron_terminal,
    _terminal,
)
from .best_response import ActorObservation, observation_for, sample_worlds


# A seat policy: (own 17-tile hand, that seat's belief pool) -> discard.
SeatPolicy = Callable[[tuple[int, ...], tuple[int, ...]], int]


def efficiency(hand17: tuple[int, ...], belief: tuple[int, ...]) -> int:
    """Production's rollout policy: maximise ukeire after the discard."""
    return _production_discard_policy(hand17, belief, 0)


def oracle_efficiency(hand17: tuple[int, ...], belief: tuple[int, ...]) -> int:
    """The reference oracle's efficiency rule, which breaks ties differently."""
    return _policy_discard(hand17, belief, 0)


def safety(hand17: tuple[int, ...], belief: tuple[int, ...]) -> int:
    """Prefer a tile whose copies are already exhausted elsewhere.

    A crude genbutsu stand-in: a tile with no unseen copies left cannot be
    waited on by a hand that needs a second copy, so it is the cheapest
    available notion of safety that needs no opponent model.  Falls back to
    efficiency among equally safe tiles, so this is a defensive *tilt* on the
    production policy rather than an unrelated third behaviour.
    """
    held = [tile for tile, count in enumerate(hand17) if count]
    safest = min(belief[tile] for tile in held)
    candidates = [tile for tile in held if belief[tile] == safest]
    if len(candidates) == 1:
        return candidates[0]
    masked = list(hand17)
    for tile in held:
        if tile not in candidates:
            masked[tile] = 0
    # Every candidate is still in the masked hand, so the efficiency rule picks
    # among exactly the safe ones.
    return _production_discard_policy(tuple(masked), belief, 0)


def deal_in_risk(hand17: tuple[int, ...], belief: tuple[int, ...]) -> int:
    """Discard the tile least likely to be waited on, then by efficiency.

    The step-3 replacement for ``safety``.  Same shape as ``safety`` -- a
    defensive tilt that falls back to the production efficiency rule among
    equally safe tiles -- so a table comparing them isolates the risk estimate
    and nothing else.

    The rule itself lives in :func:`ev._defensive_discard_policy`, in the same
    slot and signature as the production policy it tilts.  Delegating rather
    than restating it is what stops the strategy this game solved for and the
    candidate a rollout would play from drifting apart unnoticed; the endgame
    seats hold no melds, so the third argument is zero here.
    """
    return _defensive_discard_policy(hand17, belief, 0)


# Four names, three behaviours: measured 2026-08-24 over all 26 cases at 20
# worlds, ``efficiency`` and ``oracle`` pick the same tile on all 5,415
# reachable decisions, so the abstraction any claim must carry is
# {efficiency, safety} or {efficiency, deal_in_risk}.  ``oracle`` stays
# reachable because its tie-break differs in principle and a corpus that
# separated them would be worth knowing about;
# ``test_efficiency_and_oracle_are_one_behaviour_not_two`` fails if that day
# comes, which is exactly when the wording would change.
STRATEGIES: dict[str, SeatPolicy] = {
    "efficiency": efficiency,
    "oracle": oracle_efficiency,
    "safety": safety,
    "deal_in_risk": deal_in_risk,
}

# ...but it is not in the default set, because including it costs a great
# deal to learn nothing.  Measured per world at 26 cases: all-oracle 143 ms,
# all-efficiency 11.5 ms, all-safety 3.5 ms.  Of the 81 profiles over the
# full name set, 65 contain ``oracle`` and every one of them duplicates a
# profile in the 16 below -- the full-name table cost 2,462s at 20 worlds,
# where these 16 cost 833s at 400.
DEFAULT_STRATEGIES: tuple[str, ...] = ("efficiency", "safety")


def _belief(
    hand: tuple[int, ...],
    public: tuple[int, ...],
) -> tuple[int, ...]:
    counts = tuple(
        4 - hand[tile] - public[tile] for tile in range(34)
    )
    if any(count < 0 for count in counts):
        raise ValueError("public tiles exceed four physical copies")
    return counts


def profile_payoffs(
    state: ReferenceState,
    observation: ActorObservation,
    profile: tuple[str, str, str, str],
    rules: RulesConfig = DEFAULT_RULES,
) -> tuple[Fraction, Fraction, Fraction, Fraction]:
    """Exact per-*role* expectation over draw orders for one world and profile.

    ``profile`` is indexed by role, not by seat: entry ``r`` is the policy of
    the seat that draws ``r`` turns after the actor, and entry 0 is the actor.
    Returned payoffs are indexed the same way.  Everything between is still
    seat-indexed, because the wall, the settlement and the dealer are.
    """
    acting = state.acting_seat
    policies = tuple(
        STRATEGIES[profile[(seat - acting) % 4]] for seat in range(4)
    )
    totals = [Fraction(0)] * 4

    def credit(outcome, probability: Fraction) -> None:
        for seat in range(4):
            totals[seat] += probability * outcome.payment.deltas[seat]

    wall_counts = [0] * 34
    for tile in state.wall:
        wall_counts[tile] += 1

    def act(
        hands: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        seat: int,
        public: tuple[int, ...],
        probability: Fraction,
        drawn_hand: tuple[int, ...],
    ) -> None:
        chosen = policies[seat](drawn_hand, _belief(drawn_hand, public))
        if not drawn_hand[chosen]:
            raise ValueError("a seat policy returned a tile it does not hold")
        post = list(drawn_hand)
        post[chosen] -= 1
        progressed = list(hands)
        progressed[seat] = tuple(post)
        advanced = tuple(progressed)
        claims = _ron_claims(advanced, seat, chosen, rules)
        if claims:
            credit(_ron_terminal(state, claims, seat, chosen), probability)
            return
        seen = list(public)
        seen[chosen] += 1
        walk(advanced, remaining, (seat + 1) % 4, tuple(seen), probability)

    def walk(
        hands: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        seat: int,
        public: tuple[int, ...],
        probability: Fraction,
    ) -> None:
        total = sum(remaining)
        if not total:
            credit(_terminal(state, "draw", None, None), probability)
            return
        for tile, copies in enumerate(remaining):
            if not copies:
                continue
            step = probability * Fraction(copies, total)
            following = list(remaining)
            following[tile] -= 1
            drawn = list(hands[seat])
            drawn[tile] += 1
            drawn_hand = tuple(drawn)
            if _production_shanten(drawn_hand, 0) == -1:
                credit(_terminal(
                    state,
                    "self_tsumo" if seat == state.acting_seat else "opponent_tsumo",
                    seat,
                    None,
                    tile,
                    drawn_hand,
                ), step)
                continue
            act(hands, tuple(following), seat, public, step, drawn_hand)

    # The acting seat opens holding 17 tiles and owes a discard immediately.
    act(
        tuple(player.hand for player in state.players),
        tuple(wall_counts),
        state.acting_seat,
        observation.visible,
        Fraction(1),
        state.players[state.acting_seat].hand,
    )
    return tuple(totals[(acting + role) % 4] for role in range(4))


@dataclass(frozen=True)
class Regret:
    """The largest unilateral gain at a profile, with its sampling interval.

    ``low > 0`` is the only thing that licenses "this profile is not an
    equilibrium"; anything else means the budget did not resolve the question.
    """

    role: int
    reply: str
    gain: float
    low: float
    high: float

    @property
    def resolved(self) -> bool:
        """Does the interval stay clear of zero?"""
        return self.low > 0.0 or self.high < 0.0


@dataclass(frozen=True)
class EmpiricalGame:
    """Per-role payoffs for every profile over the restricted strategy set.

    The players are roles -- actor, then relative draw order 1, 2, 3 -- not
    absolute seats.  Under seat indexing a profile entry meant two different
    things in two halves of the corpus (the actor sits at seat 0 in 13 cases
    and at seat 1 in the other 13), so a payoff row averaged the actor
    deviating with a downstream seat deviating.  Role indexing does not add
    observations -- both ways give each player the same 26 case clusters -- it
    stops them from being a mixture.

    ``units`` keeps the per-(case, world) payoff vectors rather than only
    their means, because a regret without an interval cannot be reported.  The
    first full-corpus run put a single equilibrium and a regret of +0.293 tai
    on the table; the regret survived every later budget, the equilibrium did
    not survive any.  Profiles share worlds, so a deviation gain is paired per
    unit, and :meth:`regret_interval` resamples over those units' cases.
    """

    strategies: tuple[str, ...]
    payoffs: dict[tuple[str, ...], tuple[float, float, float, float]]
    units: dict[tuple[str, ...], tuple[tuple[float, float, float, float], ...]]
    cases: int
    sims: int

    def best_reply(self, profile: tuple[str, ...], role: int) -> tuple[str, float]:
        """This role's best strategy and its gain, holding the others fixed."""
        current = self.payoffs[profile][role]
        best_name, best_value = profile[role], current
        for name in self.strategies:
            candidate = list(profile)
            candidate[role] = name
            value = self.payoffs[tuple(candidate)][role]
            if value > best_value + 1e-12:
                best_name, best_value = name, value
        return best_name, best_value - current

    def equilibria(self) -> tuple[tuple[str, ...], ...]:
        """Profiles no role can improve on *by point estimate alone*.

        Read with :meth:`regret_interval`: at a thin budget this returns
        whichever profile the noise happened to favour.
        """
        return tuple(
            profile
            for profile in self.payoffs
            if all(
                self.best_reply(profile, role)[1] <= 1e-12
                for role in range(4)
            )
        )

    def regret(self, profile: tuple[str, ...]) -> float:
        """Largest unilateral gain available at ``profile``, in tai."""
        return max(
            self.best_reply(profile, role)[1] for role in range(4)
        )

    def _deviation_gains(
        self, profile: tuple[str, ...],
    ) -> dict[tuple[int, str], tuple[float, ...]]:
        """Per-case mean paired gain for each (role, alternative) deviation.

        Units arrive as ``sims`` consecutive worlds per case, and the worlds
        inside one case all share that case's hand, so they are not
        independent draws from the population a claim generalises over.  The
        case is the cluster, as in ``docs/hidden-world-strata.md``; averaging
        to it here is what makes the interval below a cluster bootstrap.
        """
        base = self.units[profile]
        if len(base) != self.cases * self.sims:
            raise ValueError("units are not sims-per-case; cannot cluster")
        gains: dict[tuple[int, str], tuple[float, ...]] = {}
        for role in range(4):
            for name in self.strategies:
                if name == profile[role]:
                    continue
                candidate = list(profile)
                candidate[role] = name
                other = self.units[tuple(candidate)]
                gains[(role, name)] = tuple(
                    sum(
                        other[i][role] - base[i][role]
                        for i in range(case * self.sims, (case + 1) * self.sims)
                    ) / self.sims
                    for case in range(self.cases)
                )
        return gains

    def regret_interval(
        self,
        profile: tuple[str, ...],
        *,
        resamples: int = 2000,
        seed: int = 7,
        confidence: float = 0.95,
    ) -> Regret:
        """Bootstrap the regret by resampling whole cases.

        Two things this gets right that the obvious version does not.  The
        maximum is taken *inside* each resample, so the interval covers the
        selection of which deviation looked best -- picking the winner first
        and bootstrapping only that one reports an interval for a role chosen
        by the same noise it is meant to measure.  And the resampled unit is
        the case, not the world: measured 2026-08-24 at 26 cases x 400 worlds,
        resampling worlds gave [+0.189, +0.340] and resampling cases
        [+0.082, +0.519] for the same +0.265 point estimate.  The wider one is
        the honest one, because 26 is how many hands were actually looked at.
        """
        gains = self._deviation_gains(profile)
        if not gains:
            raise ValueError("profile has no deviations in this strategy set")
        keys = list(gains)
        count = self.cases
        rng = Random(seed)
        draws = []
        for _ in range(resamples):
            picks = [rng.randrange(count) for _ in range(count)]
            draws.append(max(
                sum(gains[key][i] for i in picks) / count for key in keys
            ))
        draws.sort()
        tail = (1.0 - confidence) / 2.0
        low = draws[int(tail * resamples)]
        high = draws[min(resamples - 1, int((1.0 - tail) * resamples))]
        best = max(keys, key=lambda key: sum(gains[key]) / count)
        return Regret(
            role=best[0],
            reply=best[1],
            gain=sum(gains[best]) / count,
            low=low,
            high=high,
        )


def build_game(
    cases: tuple[ReferenceCase, ...],
    *,
    sims: int = 20,
    seed: int = 1,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    rules: RulesConfig = DEFAULT_RULES,
) -> EmpiricalGame:
    """Tabulate every profile's per-role payoff over the corpus.

    Profiles are indexed by role (actor first), so the same profile means the
    same thing in a case whose actor sits at seat 0 and one whose actor sits at
    seat 1.  Worlds are sampled once per case and reused across every profile,
    so profile differences are paired under common random numbers.
    """
    for name in strategies:
        if name not in STRATEGIES:
            raise ValueError(f"unknown strategy: {name}")
    sampled = []
    for case in cases:
        observation = observation_for(case)
        sampled.append((
            observation,
            sample_worlds(observation, sims, seed + case.seed),
        ))

    payoffs: dict[tuple[str, ...], tuple[float, float, float, float]] = {}
    units: dict[tuple[str, ...], tuple[tuple[float, float, float, float], ...]] = {}
    for profile in product(strategies, repeat=4):
        rows = []
        for observation, worlds in sampled:
            for world in worlds:
                rows.append(tuple(
                    float(value) for value in profile_payoffs(
                        world, observation, profile, rules,
                    )
                ))
        units[profile] = tuple(rows)
        payoffs[profile] = tuple(
            sum(row[seat] for row in rows) / len(rows) for seat in range(4)
        )
    return EmpiricalGame(tuple(strategies), payoffs, units, len(cases), sims)
