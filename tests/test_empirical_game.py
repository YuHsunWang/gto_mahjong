"""Invariants for the restricted-strategy empirical endgame game.

The claim is only as good as the tabulation under it, so these pin the
properties a broken payoff table would violate: settlement is zero-sum,
profiles are compared on shared worlds, a best reply really is the row
maximum, and a seat the wall never reaches changes nothing by exactly zero.

The slow pair at the bottom pins both halves of what step 3 concluded -- that
production's profile is not an equilibrium, and that no profile was shown to
be one.  The second matters as much as the first: it is what keeps the
"nothing was solved" wording in docs/equilibrium-plan.md from going stale
without anyone noticing.
"""

from __future__ import annotations

import pytest

from taimahjong.empirical_game import (
    STRATEGIES,
    build_game,
    efficiency,
    oracle_efficiency,
    profile_payoffs,
    safety,
)
from taimahjong.best_response import observation_for, sample_worlds
from taimahjong.reference_ev import representative_reference_cases


CASES = representative_reference_cases()
SMALL = CASES[:3]


def test_every_profile_settles_zero_sum():
    """Four-seat settlement moves value between seats and never creates it, so
    any profile whose payoffs do not cancel means the tabulation is wrong."""
    game = build_game(SMALL, sims=3, seed=1)
    for profile, payoffs in game.payoffs.items():
        assert sum(payoffs) == pytest.approx(0.0, abs=1e-9), profile


def test_one_world_is_exact_and_zero_sum():
    """Per world the draw-order expectation is exact rational arithmetic, so
    this cancels exactly rather than approximately."""
    case = next(case for case in CASES if len(case.state.wall) == 4)
    observation = observation_for(case)
    world = sample_worlds(observation, 1, 5)[0]
    payoffs = profile_payoffs(world, observation, ("efficiency",) * 4)
    assert sum(payoffs) == 0


def test_best_reply_is_the_row_maximum():
    """A best reply must beat every alternative for that seat, holding the
    rest of the profile fixed; anything less means the search is skipping."""
    game = build_game(SMALL, sims=3, seed=1)
    profile = ("efficiency",) * 4
    for seat in range(4):
        name, gain = game.best_reply(profile, seat)
        assert gain >= 0.0
        for alternative in game.strategies:
            candidate = list(profile)
            candidate[seat] = alternative
            assert (
                game.payoffs[tuple(candidate)][seat]
                <= game.payoffs[profile][seat] + gain + 1e-12
            )


def test_equilibria_have_no_profitable_deviation():
    """The definition, restated as a check on the returned set."""
    game = build_game(SMALL, sims=3, seed=1)
    for profile in game.equilibria():
        assert game.regret(profile) <= 1e-12, profile


def test_safety_only_ever_discards_a_held_tile():
    """The safety tilt masks the hand before delegating, which would return a
    tile the seat does not hold if the masking were wrong."""
    case = next(case for case in CASES if len(case.state.wall) == 4)
    observation = observation_for(case)
    for world in sample_worlds(observation, 4, 7):
        for player in world.players:
            hand = player.hand
            if sum(hand) != 17:
                continue
            belief = tuple(
                4 - hand[tile] - observation.visible[tile] for tile in range(34)
            )
            assert hand[safety(hand, belief)] > 0


def test_efficiency_and_oracle_are_one_behaviour_not_two():
    """The abstraction is two behaviours wide, not three.

    Measured 2026-08-24 over all 26 cases at 20 worlds: the two efficiency
    rules pick the same tile on all 5,415 reachable decisions, so a profile
    that only swaps one for the other is the same profile played twice.  Any
    claim built on this game has to count the set as {efficiency, safety};
    this fails the moment that stops being true, which is the point at which
    the claim would need rewording.
    """
    agree = disagree = 0
    for case in SMALL:
        observation = observation_for(case)
        for world in sample_worlds(observation, 3, 1 + case.seed):
            for player in world.players:
                hand = player.hand
                if sum(hand) != 17:
                    continue
                belief = tuple(
                    4 - hand[tile] - observation.visible[tile] for tile in range(34)
                )
                assert efficiency(hand, belief) == oracle_efficiency(hand, belief)
                if safety(hand, belief) == efficiency(hand, belief):
                    agree += 1
                else:
                    disagree += 1
    # A safety tilt that never tilts would make the game one strategy wide and
    # every equilibrium trivial, so pin that it actually diverges.
    assert disagree > 0, (agree, disagree)


def test_a_seat_the_wall_never_reaches_cannot_change_anything():
    """The sharpest structural check available: exact zeros.

    With ``w`` tiles left, only relative positions 1..w after the actor ever
    draw, so a seat past that never discards and its strategy cannot move any
    payoff by any amount.  Verified 2026-08-24 over 4,000 such unit
    observations at 400 worlds: every gain was exactly 0.0, not merely small.
    Leaking hidden state or misaligning a seat index would perturb these.
    """
    E, S = "efficiency", "safety"
    checked = 0
    for case in CASES:
        wall = len(case.state.wall)
        idle = [
            seat for seat in range(4)
            if (seat - case.state.acting_seat) % 4 > wall
        ]
        if not idle:
            continue
        observation = observation_for(case)
        for world in sample_worlds(observation, 2, 1 + case.seed):
            base = profile_payoffs(world, observation, (E,) * 4)
            for seat in idle:
                profile = list((E,) * 4)
                profile[seat] = S
                assert profile_payoffs(world, observation, tuple(profile)) == base
                checked += 1
    assert checked, "corpus no longer contains a seat the wall cannot reach"


def test_strategy_set_is_listed_not_inferred():
    """Claims built on this module must carry the strategy set, so the set is
    explicit and the game records the one it was built with."""
    game = build_game(SMALL, sims=3, seed=1, strategies=("efficiency", "safety"))
    assert game.strategies == ("efficiency", "safety")
    assert len(game.payoffs) == 2 ** 4
    with pytest.raises(ValueError):
        build_game(SMALL, sims=3, seed=1, strategies=("efficiency", "nope"))
    assert set(STRATEGIES) == {"efficiency", "oracle", "safety"}


def test_identical_strategies_leave_exactly_nothing_on_the_table():
    """End-to-end check of the interval with an answer known in advance.

    ``efficiency`` and ``oracle`` never differ on this corpus, so every
    deviation gain is exactly zero unit by unit, and no resample of zeros can
    be anything but zero.  A pipeline that mismatched units between profiles,
    or paired the wrong seat, could not produce this.
    """
    game = build_game(SMALL, sims=3, seed=1, strategies=("efficiency", "oracle"))
    profile = ("efficiency",) * 4
    result = game.regret_interval(profile, resamples=200)
    assert result.gain == 0.0
    assert (result.low, result.high) == (0.0, 0.0)
    assert not result.resolved


def test_regret_interval_and_regret_agree_on_the_point_estimate():
    """``regret`` floors at zero because staying put is always available;
    ``regret_interval`` reports the best deviation unfloored so the interval
    can show it is unprofitable.  Past the floor they must be the same
    number, or the two are reading different tables."""
    game = build_game(SMALL, sims=3, seed=1)
    for profile in game.payoffs:
        result = game.regret_interval(profile, resamples=100)
        assert game.regret(profile) == pytest.approx(
            max(0.0, result.gain), abs=1e-9,
        )
        assert result.low <= result.high


@pytest.fixture(scope="module")
def corpus_game():
    """The corpus game at a budget the two slow claims can both be read off.

    100 worlds costs ~130s and is the cheapest budget whose interval clears
    zero with room: seeds 1/2/3 gave lower bounds +0.064/+0.127/+0.074, all
    naming seat 0 -> safety.  The reported measurement is at 400 worlds
    (docs/equilibrium-plan.md); this only has to pin the claim, not restate
    its precision.
    """
    return build_game(CASES, sims=100, seed=1)


@pytest.mark.slow
def test_the_production_profile_is_shown_not_to_be_an_equilibrium(corpus_game):
    """The headline result.

    Recorded 2026-08-24 at 26 cases x 400 worlds: regret +0.265 tai, 95% CI
    [+0.082, +0.519] resampling cases, best deviation seat 0 -> safety.  The
    interval clearing zero is the whole claim -- the point estimate alone
    survived every budget while the equilibrium it implied did not.
    """
    result = corpus_game.regret_interval(("efficiency",) * 4)
    assert result.resolved and result.low > 0.0, result
    assert (result.seat, result.reply) == (0, "safety"), result


@pytest.mark.slow
def test_no_profile_in_this_abstraction_is_shown_to_be_an_equilibrium(corpus_game):
    """Guards the *negative* half of the step 3 writeup.

    Being an equilibrium means no deviation pays, which this budget can only
    show by putting the regret interval entirely below zero.  At 400 worlds no
    profile managed it and five stayed unresolved.  If one ever does, the
    "no equilibrium was solved" wording in docs/equilibrium-plan.md is stale
    and should fail here rather than quietly stay in the file.
    """
    solved = [
        profile for profile in corpus_game.payoffs
        if corpus_game.regret_interval(profile).high < 0.0
    ]
    assert not solved, solved
