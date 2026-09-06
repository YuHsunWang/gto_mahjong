"""Information-set best response and exploitability for the shallow endgame.

This module answers one narrow question: in the same at-most-four-tile-wall,
no-call subgame that :mod:`taimahjong.reference_ev` already settles exactly,
how much value does the production rollout policy leave on the table against a
best response that is restricted to the acting seat's information?

Two layers, with different error properties:

* **Wall order stays exact.**  Within one sampled world every physical draw
  order is enumerated with :class:`~fractions.Fraction`, so the per-world value
  carries no sampling error at all.
* **Hidden hands are sampled.**  The acting seat cannot see 3x16 opponent tiles
  plus the wall, and that information set has on the order of 10^26 members, so
  it is estimated rather than enumerated.  Exploitability therefore comes with
  a confidence interval, not as an exact rational.

The in-sample estimate evaluates both policies on the *same* sampled worlds,
so their difference is paired under common random numbers, exactly as
``paired_delta_moments`` is for production EV.  An optional opening-only
holdout instead fits the best-response opening on the first half of a sample
and applies it to the second half.  Those disjoint roles remove winner's curse
from the reported point estimate.

Two invariants make the information-set restriction testable, because a plan
that leaks hidden state would silently inflate the answer rather than fail:

* in-sample exploitability is never negative -- the best response can always
  copy the production action on its fitting worlds, so a negative estimate is
  a bug, not a finding;
* feeding the solved best response back in as the measured policy yields
  exactly zero.

**Both policies are restricted to the same information.**  The production
rollout policy is normally called with the rollout's true remaining wall, which
is hidden from a real player.  Here the acting seat's own decisions instead
receive its belief pool (four copies minus its hand, minus everything visible,
minus what it has since watched being discarded).  Without that the measured
policy would see more than the best response and the non-negativity invariant
would be meaningless.  Opponents remain part of the environment and are driven
exactly as production drives them.

Scope, and it is narrow: at most a four-tile wall, no calls, no flowers, and
the acting seat's opponent-belief model is production's own.  The number
therefore isolates *policy* error; belief-model error is a separate question
this module does not answer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction
from math import ceil

from .calibration import Calibration
from .config import DEFAULT_RULES, RulesConfig
from .danger import OpponentView
from .ev import (
    _fold_choice,
    _production_discard_policy,
    _sample_production_world,
    _production_shanten,
    ev_rank,
)
from .moments import SampleMoments
from .reference_ev import (
    ReferenceCase,
    ReferencePlayer,
    ReferenceState,
    _ron_claims,
    _ron_terminal,
    _terminal,
)
from .rollout import DiscardPolicy
from .scoring import ScoringScheme, WinContext
from .tiles import validate_counts


@dataclass(frozen=True)
class ActorObservation:
    """Everything the acting seat can see, and nothing it cannot."""

    hand: tuple[int, ...]
    visible: tuple[int, ...]
    views: tuple[OpponentView, ...]
    wall_size: int
    acting_seat: int
    next_seat: int
    dealer_streak: int
    scheme: ScoringScheme

    def __post_init__(self) -> None:
        if sum(self.hand) != 17:
            raise ValueError("the acting seat observes a 17-tile post-draw hand")
        if not 0 <= self.wall_size <= 4:
            raise ValueError("this module is scoped to walls of at most four tiles")
        if self.next_seat != (self.acting_seat + 1) % 4:
            raise ValueError("play must resume at the seat after the actor")

    @property
    def context(self) -> WinContext:
        return WinContext(
            winning_tile=0,
            dealer=self.acting_seat == 0,
            dealer_streak=self.dealer_streak if self.acting_seat == 0 else 0,
        )

    def belief_remaining(
        self,
        hand: tuple[int, ...] | None = None,
        observed: tuple[tuple[int, int], ...] = (),
    ) -> tuple[int, ...]:
        """Unseen copies of every tile, from the acting seat's point of view."""
        held = self.hand if hand is None else hand
        counts = [
            4 - held[tile] - self.visible[tile]
            for tile in range(34)
        ]
        for _, tile in observed:
            counts[tile] -= 1
        if any(count < 0 for count in counts):
            raise ValueError("observed tiles exceed four physical copies")
        return tuple(counts)


def observation_for(case: ReferenceCase) -> ActorObservation:
    """Project a reference case onto what its acting seat can actually see.

    This mirrors the view ``reference_ev.compare_reference_corpus`` hands to
    ``ev_rank`` so the sampled worlds share production's belief model.
    """
    state = case.state
    visible = [0] * 34
    views: list[OpponentView] = []
    for ordinal, seat in enumerate(
        seat for seat in range(4) if seat != state.acting_seat
    ):
        player = state.players[seat]
        river = [15 + ordinal] if player.declared_at is not None else []
        if river:
            visible[river[0]] += 1
        views.append(OpponentView(
            river,
            [],
            declared_at=0 if player.declared_at is not None else None,
            is_dealer=seat == 0,
            dealer_streak=state.dealer_streak if seat == 0 else 0,
            hand_count=16,
        ))
    return ActorObservation(
        validate_counts(state.players[state.acting_seat].hand),
        tuple(visible),
        tuple(views),
        len(state.wall),
        state.acting_seat,
        state.next_seat,
        state.dealer_streak,
        state.scheme,
    )


@dataclass(frozen=True)
class ProductionRankChoice:
    """Production's root choice paired with its own continuation rule."""

    discard: int
    continuation: DiscardPolicy
    is_fold: bool


def production_rank_policy(
    observation: ActorObservation,
    *,
    sims: int,
    seed: int,
    calibration: Calibration | None = None,
) -> ProductionRankChoice:
    """Return production's root discard and that branch's continuation.

    Production ranks push lines and one separately priced fold line, then
    chooses between all of them by net EV.  Reusing only its hand-based rollout
    rule here would remove that root fold choice and measure a policy production
    never actually plays.  The rank is built from the actor's observation only;
    hidden reference players and the true wall must stay outside this call.

    A fold continuation needs the public count after later watched discards.
    ``remaining`` already excludes both the actor's current hand and every tile
    watched since the root, so four minus those two quantities reconstructs the
    exact visible count without widening :class:`DiscardPolicy`.
    """
    ranked = ev_rank(
        observation.hand,
        observation.views,
        observation.visible,
        turns=max(1, ceil(observation.wall_size / 4)),
        sims=sims,
        seed=seed,
        context_template=observation.context,
        calibration=calibration,
        scheme=observation.scheme,
    )
    winner = max(
        ranked,
        key=lambda entry: (
            entry.net_ev,
            -entry.discard,
            not entry.is_fold,
        ),
    )
    if not winner.is_fold:
        return ProductionRankChoice(
            winner.discard, _production_discard_policy, False,
        )

    def fold_continuation(
        hand17: tuple[int, ...],
        remaining: tuple[int, ...],
        _melds_declared: int,
    ) -> int:
        visible = tuple(
            4 - hand17[tile] - remaining[tile]
            for tile in range(34)
        )
        return _fold_choice(
            hand17,
            visible,
            observation.views,
            calibration,
            observation.scheme,
        )

    return ProductionRankChoice(winner.discard, fold_continuation, True)


def sample_worlds(
    observation: ActorObservation,
    sims: int,
    seed: int,
) -> tuple[ReferenceState, ...]:
    """Draw worlds consistent with ``observation`` from production's belief.

    Worlds whose opponents are dealt an already-complete hand are rejected and
    redrawn: such a seat would have won before this decision, so the state is
    not reachable.
    """
    if sims < 1:
        raise ValueError("sims must be positive")
    rng = random.Random(seed)
    worlds: list[ReferenceState] = []
    attempts = 0
    while len(worlds) < sims:
        attempts += 1
        if attempts > 100 * sims:
            raise RuntimeError("could not sample enough reachable worlds")
        trial = _sample_production_world(
            observation.hand,
            observation.visible,
            observation.views,
            1,
            observation.context,
            rng.randrange(2**64),
        )
        hands = tuple(tuple(player.hand) for player in trial.players)
        if any(
            seat != observation.acting_seat and _production_shanten(hand, 0) == -1
            for seat, hand in enumerate(hands)
        ):
            continue
        worlds.append(ReferenceState(
            tuple(
                ReferencePlayer(
                    tuple(player.hand), declared_at=player.declared_at,
                )
                for player in trial.players
            ),
            tuple(trial.wall[:observation.wall_size]),
            acting_seat=observation.acting_seat,
            next_seat=observation.next_seat,
            dealer_streak=observation.dealer_streak,
            scheme=observation.scheme,
        ))
    return tuple(worlds)


# An actor information set: its own hand, plus the discards it has watched
# since its own.  Nothing else may enter this key -- adding any hidden term
# turns the solved plan into a clairvoyant one that quietly reads too high.
InfoKey = tuple[tuple[int, ...], tuple[tuple[int, int], ...]]
# contributions[key][action] = expected actor payment routed through that node
Contributions = dict[InfoKey, dict[int, Fraction]]


def _analyse_opening(
    state: ReferenceState,
    observation: ActorObservation,
    discard: int,
    rules: RulesConfig,
) -> tuple[Fraction, Contributions]:
    """Enumerate one world exactly, split by the actor's later decision.

    Returns the value that does not depend on the actor's second action, plus
    the value routed through each (information set, action) pair.  Every
    enumerated path passes through at most one actor decision, which is what
    makes this split exact; a deeper wall would break it and raises instead.
    """
    hands = [player.hand for player in state.players]
    actor = list(hands[state.acting_seat])
    if not actor[discard]:
        raise ValueError("discard must be present in the acting hand")
    actor[discard] -= 1
    hands[state.acting_seat] = tuple(actor)
    frozen = tuple(hands)

    base = Fraction(0)
    contributions: Contributions = {}

    immediate = _ron_claims(frozen, state.acting_seat, discard, rules)
    if immediate:
        outcome = _ron_terminal(state, immediate, state.acting_seat, discard)
        return Fraction(outcome.payment.deltas[state.acting_seat]), contributions

    wall_counts = [0] * 34
    for tile in state.wall:
        wall_counts[tile] += 1

    def payment(outcome) -> Fraction:
        return Fraction(outcome.payment.deltas[state.acting_seat])

    def walk(
        current: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        seat: int,
        probability: Fraction,
        observed: tuple[tuple[int, int], ...],
        actor_acted: bool,
        sink: dict[int, Fraction] | None,
        action: int | None,
    ) -> None:
        """Walk one subtree.

        ``sink``/``action`` are set once the path has passed through an actor
        decision: everything below then accrues to that (info set, action)
        pair rather than to ``base``.
        """
        nonlocal base

        def credit(value: Fraction) -> None:
            nonlocal base
            if sink is None:
                base += value
            else:
                sink[action] = sink.get(action, Fraction(0)) + value

        total = sum(remaining)
        if not total:
            credit(probability * payment(_terminal(state, "draw", None, None)))
            return
        for tile, copies in enumerate(remaining):
            if not copies:
                continue
            next_probability = probability * Fraction(copies, total)
            next_remaining = list(remaining)
            next_remaining[tile] -= 1
            drawn = list(current[seat])
            drawn[tile] += 1
            drawn_hand = tuple(drawn)
            if _production_shanten(drawn_hand, 0) == -1:
                credit(next_probability * payment(_terminal(
                    state,
                    "self_tsumo" if seat == state.acting_seat else "opponent_tsumo",
                    seat,
                    None,
                    tile,
                    drawn_hand,
                )))
                continue

            if seat == state.acting_seat:
                if actor_acted:
                    raise RuntimeError(
                        "a path reached a second actor decision; this module "
                        "is scoped to walls that allow only one"
                    )
                key: InfoKey = (drawn_hand, observed)
                node = contributions.setdefault(key, {})
                for candidate in range(34):
                    if not drawn_hand[candidate]:
                        continue
                    _continue_after_discard(
                        current,
                        tuple(next_remaining),
                        seat,
                        next_probability,
                        observed,
                        drawn_hand,
                        candidate,
                        True,
                        node,
                        candidate,
                    )
                continue

            chosen = (
                tile
                if state.players[seat].declared_at is not None
                else _production_discard_policy(
                    drawn_hand, tuple(next_remaining), 0,
                )
            )
            _continue_after_discard(
                current,
                tuple(next_remaining),
                seat,
                next_probability,
                observed,
                drawn_hand,
                chosen,
                actor_acted,
                sink,
                action,
            )

    def _continue_after_discard(
        current: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        seat: int,
        probability: Fraction,
        observed: tuple[tuple[int, int], ...],
        drawn_hand: tuple[int, ...],
        chosen: int,
        actor_acted: bool,
        sink: dict[int, Fraction] | None,
        action: int | None,
    ) -> None:
        nonlocal base

        def credit(value: Fraction) -> None:
            nonlocal base
            if sink is None:
                base += value
            else:
                sink[action] = sink.get(action, Fraction(0)) + value

        post = list(drawn_hand)
        post[chosen] -= 1
        progressed = list(current)
        progressed[seat] = tuple(post)
        advanced = tuple(progressed)
        claims = _ron_claims(advanced, seat, chosen, rules)
        if claims:
            credit(probability * payment(
                _ron_terminal(state, claims, seat, chosen)
            ))
            return
        next_observed = (
            observed
            if seat == state.acting_seat
            else observed + ((seat, chosen),)
        )
        walk(
            advanced,
            remaining,
            (seat + 1) % 4,
            probability,
            next_observed,
            actor_acted,
            sink,
            action,
        )

    walk(
        frozen,
        tuple(wall_counts),
        state.next_seat,
        Fraction(1),
        (),
        False,
        None,
        None,
    )
    return base, contributions


def _production_action(
    observation: ActorObservation,
    key: InfoKey,
    policy: DiscardPolicy = _production_discard_policy,
) -> int:
    """What the measured rollout policy plays at one actor information set.

    ``policy`` defaults to production's, which is what the reported number
    measures.  Substituting another policy measures that one against the same
    fixed environment: the opponents in :func:`_analyse_opening` keep playing
    production's rule either way, so the two numbers stay comparable.
    """
    hand, observed = key
    return policy(
        hand, observation.belief_remaining(hand, observed), 0,
    )


@dataclass(frozen=True)
class ExploitabilityResult:
    """One case's measured gap between best response and measured policy.

    ``holdout_exploitability`` may be negative.  It compares two estimators on
    worlds that did not choose the best-response opening, so the in-sample gap
    remains the non-negative information-leakage sentinel.
    """

    name: str
    sims: int
    best_response_ev: float
    production_ev: float
    exploitability: float
    production_discard: int
    best_response_discard: int
    moments: SampleMoments
    information_sets: int
    # None in clairvoyant mode, where the plan is per world by construction.
    plan: dict[InfoKey, int] | None = None
    clairvoyant: bool = False
    # Information sets reached by more than one world.  Zero of these on a
    # corpus with shared keys would mean hidden state had leaked into the key.
    shared_information_sets: int = 0
    holdout_exploitability: float | None = None

    @property
    def ci95(self) -> tuple[float, float] | None:
        return self.moments.ci95


def _plan_value(
    contributions: Contributions,
    plan: dict[InfoKey, int],
) -> Fraction:
    """Value routed through actor decisions when ``plan`` is followed.

    Every action set is a function of the key's own hand, so a solved plan is
    playable in any world that reaches the key; a KeyError here means the plan
    and the keys disagree, which is a bug rather than a state to tolerate.
    """
    return sum(
        (node[plan[key]] for key, node in contributions.items()),
        Fraction(0),
    )


def _greedy_plan(contributions: Contributions) -> dict[InfoKey, int]:
    return {
        key: max(node, key=lambda action: (node[action], -action))
        for key, node in contributions.items()
    }


def _merge(analyses: list[tuple[Fraction, Contributions]]) -> tuple[Fraction, Contributions, int]:
    """Pool one opening discard's per-world contributions by information set."""
    merged: Contributions = {}
    reached: dict[InfoKey, int] = {}
    total_base = Fraction(0)
    for base, contributions in analyses:
        total_base += base
        for key, node in contributions.items():
            reached[key] = reached.get(key, 0) + 1
            target = merged.setdefault(key, {})
            for action, value in node.items():
                target[action] = target.get(action, Fraction(0)) + value
    shared = sum(1 for count in reached.values() if count > 1)
    return total_base, merged, shared


def exploitability(
    case: ReferenceCase,
    *,
    sims: int = 200,
    seed: int | None = None,
    rules: RulesConfig = DEFAULT_RULES,
    mode: str = "opening",
    measured_opening: int | None = None,
    measured_plan: dict[InfoKey, int] | None = None,
    measured_policy: DiscardPolicy = _production_discard_policy,
    holdout: bool = False,
) -> ExploitabilityResult:
    """Measure how much the measured policy leaves on the table in ``case``.

    By default the measured policy is production's rollout policy, restricted
    to the acting seat's information exactly as the best response is.  Passing
    ``measured_opening`` substitutes another root choice.  An optional
    ``measured_plan`` substitutes its covered continuation information sets,
    which is what lets a test feed the solved best response back in and require
    zero.  Without a plan, ``measured_policy`` supplies the continuation.

    ``measured_policy`` swaps the acting seat's rule for a whole other policy
    of the same shape.  Only the actor's rule changes: the opponents inside
    :func:`_analyse_opening` stay on production's, so two policies measured
    this way face the same environment and their numbers may be compared.  What
    this cannot measure is a policy whose point is what the *opponents* do
    differently -- that needs the empirical game, not this module.

    Three modes, because only one of them is a sound information-set number:

    ``"opening"`` (default) optimises the opening discard alone and leaves the
    continuation on the measured policy.  Every sampled world sits in the one
    information set the case defines, so this is a proper information-set best
    response with no degeneracy -- and it is the decision ``ev_rank`` exists to
    make.

    ``"clairvoyant"`` lets the best response pick a different continuation per
    world.  That is an upper bound on exploitability, not exploitability: it
    also collects the value of seeing hidden state.

    ``"full"`` asks for an information-set best response over the whole policy.
    Do not read its number as exploitability.  The acting seat observes its own
    draw and all three opponent discards, so the depth-two information sets are
    almost surely singletons at any affordable sample size -- measured at 200
    worlds, 17 of 3,170 sets were reached twice -- and the solved plan overfits
    its own world until the answer equals ``"clairvoyant"``.  The mode is kept
    so the degeneracy stays measurable through ``shared_information_sets``.

    ``holdout=True`` is available only for ``"opening"``.  It draws twice the
    requested worlds, estimates the best-response opening on the first half,
    and applies it to the second half.  The estimating and applying sample
    indices are disjoint.  A clairvoyant plan is fitted per world and cannot
    transfer to new worlds, while ``"full"`` has the singleton degeneracy
    above.  The holdout gap may be negative because it is the difference
    between two estimators on worlds that neither one was selected upon.
    """
    if mode not in ("opening", "clairvoyant", "full"):
        raise ValueError("mode must be 'opening', 'clairvoyant', or 'full'")
    if holdout and mode != "opening":
        raise ValueError("holdout is available only in 'opening' mode")
    clairvoyant = mode == "clairvoyant"
    observation = observation_for(case)
    sampled_worlds = sample_worlds(
        observation, sims * 2 if holdout else sims,
        case.seed if seed is None else seed,
    )
    worlds = sampled_worlds[:sims]
    holdout_worlds = sampled_worlds[sims:] if holdout else ()
    discards = tuple(tile for tile in range(34) if observation.hand[tile])
    analyses = [
        [
            _analyse_opening(world, observation, discard, rules)
            for discard in discards
        ]
        for world in worlds
    ]
    holdout_analyses = [
        [
            _analyse_opening(world, observation, discard, rules)
            for discard in discards
        ]
        for world in holdout_worlds
    ]

    if measured_opening is None and measured_plan is not None:
        raise ValueError("measured_plan requires measured_opening")
    opening_discard = (
        measured_policy(
            observation.hand, observation.belief_remaining(), 0,
        )
        if measured_opening is None
        else measured_opening
    )
    if not observation.hand[opening_discard]:
        raise ValueError("measured opening discard is not in the acting hand")

    def measured_action(key: InfoKey) -> int:
        """The measured policy's action at one actor information set.

        An injected plan describes a deviation only at the information sets it
        covers -- those reachable after its own opening discard.  The best
        response also explores other openings, and off that path the measured
        policy is production's, so an uncovered key falls back rather than
        failing.
        """
        if measured_plan is None:
            return _production_action(observation, key, measured_policy)
        # Tile 0 is a legal action, so test for absence rather than falsiness.
        action = measured_plan.get(key)
        if action is None:
            return _production_action(observation, key, measured_policy)
        return action

    best_totals: dict[int, Fraction] = {}
    plans: dict[int, dict[InfoKey, int] | None] = {}
    per_world_plans: dict[int, list[dict[InfoKey, int]]] = {}
    shared_counts: dict[int, int] = {}
    bases: dict[int, Fraction] = {}
    for index, discard in enumerate(discards):
        column = [world_analyses[index] for world_analyses in analyses]
        total_base, merged, shared = _merge(column)
        bases[discard] = total_base
        shared_counts[discard] = shared
        if clairvoyant:
            plans[discard] = None
            world_plans = [
                _greedy_plan(contributions) for _, contributions in column
            ]
        elif mode == "opening":
            # The continuation stays on the measured policy; only the opening
            # discard is optimised, and every world shares that information set.
            plan = {
                key: measured_action(key) for key in merged
            }
            plans[discard] = plan
            world_plans = [plan] * len(column)
        else:
            plan = _greedy_plan(merged)
            plans[discard] = plan
            world_plans = [plan] * len(column)
        per_world_plans[discard] = world_plans
        best_totals[discard] = total_base + sum(
            (
                _plan_value(contributions, world_plans[position])
                for position, (_, contributions) in enumerate(column)
            ),
            Fraction(0),
        )

    best_discard = max(discards, key=lambda tile: (best_totals[tile], -tile))
    best_index = discards.index(best_discard)
    measured_index = discards.index(opening_discard)

    measured_total = bases[opening_discard] + sum(
        (
            sum(
                (node[measured_action(key)] for key, node in contributions.items()),
                Fraction(0),
            )
            for _, contributions in (
                world_analyses[measured_index] for world_analyses in analyses
            )
        ),
        Fraction(0),
    )

    differences: list[float] = []
    for position, world_analyses in enumerate(analyses):
        best_base, best_contributions = world_analyses[best_index]
        best_value = best_base + _plan_value(
            best_contributions, per_world_plans[best_discard][position],
        )
        measured_base, measured_contributions = world_analyses[measured_index]
        measured_value = measured_base + sum(
            (
                node[measured_action(key)]
                for key, node in measured_contributions.items()
            ),
            Fraction(0),
        )
        differences.append(float(best_value - measured_value))

    moments = SampleMoments.from_values(tuple(differences), post_selection=True)
    best_response_ev = float(best_totals[best_discard]) / len(worlds)
    measured_ev = float(measured_total) / len(worlds)
    gap = best_response_ev - measured_ev
    if gap < -1e-9:
        raise RuntimeError(
            "negative exploitability: the best response is leaking information "
            f"or the plan is inconsistent (gap={gap!r})"
        )
    holdout_gap = None
    if holdout:
        holdout_differences: list[float] = []
        for world_analyses in holdout_analyses:
            best_base, best_contributions = world_analyses[best_index]
            best_value = best_base + sum(
                (
                    node[measured_action(key)]
                    for key, node in best_contributions.items()
                ),
                Fraction(0),
            )
            measured_base, measured_contributions = world_analyses[measured_index]
            measured_value = measured_base + sum(
                (
                    node[measured_action(key)]
                    for key, node in measured_contributions.items()
                ),
                Fraction(0),
            )
            holdout_differences.append(float(best_value - measured_value))
        holdout_gap = sum(holdout_differences) / len(holdout_differences)
    return ExploitabilityResult(
        case.name,
        len(worlds),
        best_response_ev,
        measured_ev,
        max(0.0, gap),
        opening_discard,
        best_discard,
        moments,
        len(per_world_plans[best_discard][0]) if clairvoyant else len(plans[best_discard]),
        plans[best_discard],
        clairvoyant,
        shared_counts[best_discard],
        holdout_gap,
    )
