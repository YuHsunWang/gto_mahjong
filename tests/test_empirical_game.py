"""Invariants for the restricted-strategy empirical endgame game.

The claim is only as good as the tabulation under it, so these pin the
properties a broken payoff table would violate: settlement is zero-sum,
profiles are compared on shared worlds, a best reply really is the row
maximum, and a role the wall never reaches changes nothing by exactly zero.

The players are roles -- actor, then relative draw order 1, 2, 3 -- so a
profile entry means the same thing in the 13 cases whose actor sits at seat 0
and the 13 whose actor sits at seat 1.  The role-to-seat rotation lives in
``profile_payoffs``; the exact-zeros test is what pins it.

The slow pair at the bottom pins both halves of what step 3 concluded -- that
production's profile is not an equilibrium, and that no profile was shown to
be one.  The second matters as much as the first: it is what keeps the
"nothing was solved" wording in docs/equilibrium-plan.md from going stale
without anyone noticing.
"""

from __future__ import annotations

import pytest

from taimahjong.danger import deal_in_weight
from taimahjong.empirical_game import (
    STRATEGIES,
    build_game,
    deal_in_risk,
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
    """A best reply must beat every alternative for that role, holding the
    rest of the profile fixed; anything less means the search is skipping."""
    game = build_game(SMALL, sims=3, seed=1)
    profile = ("efficiency",) * 4
    for role in range(4):
        name, gain = game.best_reply(profile, role)
        assert gain >= 0.0
        for alternative in game.strategies:
            candidate = list(profile)
            candidate[role] = alternative
            assert (
                game.payoffs[tuple(candidate)][role]
                <= game.payoffs[profile][role] + gain + 1e-12
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


def test_deal_in_risk_only_ever_discards_a_held_tile():
    """Same masking contract as the safety tilt: a wrong mask would hand back
    a tile the seat does not hold."""
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
            assert hand[deal_in_risk(hand, belief)] > 0


def test_a_tile_with_no_unseen_copies_is_not_automatically_safe():
    """This is the gap ``deal_in_risk`` exists to close.

    ``safety`` reads one bit -- are there unseen copies? -- so a tile whose
    other copies are all accounted for looks perfectly safe to it.  That is
    only true of the waits needing a *second* copy of the tile (tanki,
    shanpon).  A two-sided wait needs the tile's neighbours instead, so an
    opponent holding 3p4p is waiting on 2p and 5p however many 5p are already
    visible.  ``deal_in_risk`` must therefore rank such a tile as more
    dangerous than one that still has a copy unseen but whose neighbours are
    exhausted -- the ordering ``safety`` gets backwards.
    """
    pool = 60
    reachable_belief = [0] * 34
    for tile in (11, 12, 14, 15):  # 3p 4p 6p 7p live, so ryanmen waits exist
        reachable_belief[tile] = 4
    reachable_belief[13] = 0  # 5p itself: no copies unseen

    isolated_belief = [0] * 34
    isolated_belief[4] = 1  # 5m: a copy unseen, but nothing around it survives

    reachable = deal_in_weight(13, tuple(reachable_belief), pool)
    isolated = deal_in_weight(4, tuple(isolated_belief), pool)
    assert reachable > isolated


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


def test_a_role_the_wall_never_reaches_cannot_change_anything():
    """The sharpest structural check available: exact zeros.

    With ``w`` tiles left, only roles 1..w ever draw, so a role past that never
    discards and its strategy cannot move any payoff by any amount.  Verified
    2026-08-24 over 4,000 such unit observations at 400 worlds: every gain was
    exactly 0.0, not merely small.  Leaking hidden state would perturb these,
    and so would a wrong role-to-seat rotation: the idle role is stated here in
    role terms and resolved to a seat inside ``profile_payoffs``.  That is not
    vacuous -- checked 2026-08-25, the two wall-2 cases whose actor sits at
    seat 1 have idle role 3, and the seat that entry 3 would name without the
    rotation is one the wall does reach, whose tilt moves payoffs in 2 of 8
    sampled worlds.  Reading profiles as seats fails here.
    """
    E, S = "efficiency", "safety"
    checked = 0
    for case in CASES:
        wall = len(case.state.wall)
        idle = [role for role in range(4) if role > wall]
        if not idle:
            continue
        observation = observation_for(case)
        for world in sample_worlds(observation, 2, 1 + case.seed):
            base = profile_payoffs(world, observation, (E,) * 4)
            for role in idle:
                profile = list((E,) * 4)
                profile[role] = S
                assert profile_payoffs(world, observation, tuple(profile)) == base
                checked += 1
    assert checked, "corpus no longer contains a role the wall cannot reach"


def test_strategy_set_is_listed_not_inferred():
    """Claims built on this module must carry the strategy set, so the set is
    explicit and the game records the one it was built with."""
    game = build_game(SMALL, sims=3, seed=1, strategies=("efficiency", "safety"))
    assert game.strategies == ("efficiency", "safety")
    assert len(game.payoffs) == 2 ** 4
    with pytest.raises(ValueError):
        build_game(SMALL, sims=3, seed=1, strategies=("efficiency", "nope"))
    assert set(STRATEGIES) == {
        "efficiency", "oracle", "safety", "deal_in_risk",
    }


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

    100 worlds costs ~150s and clears zero with room: measured 2026-08-25 on
    the role-indexed game, world seeds 1/2/3 gave lower bounds
    +0.078/+0.147/+0.087, all naming role 0 -> safety, and none of the three
    put any profile below zero.  The reported measurement is at 400 worlds
    (docs/equilibrium-plan.md); this only has to pin the claim, not restate
    its precision.
    """
    return build_game(CASES, sims=100, seed=1)


@pytest.mark.slow
def test_the_production_profile_is_shown_not_to_be_an_equilibrium(corpus_game):
    """The headline result.

    Re-measured 2026-09-05 on the role-indexed game at 26 cases x 100 worlds:
    regret +0.611 tai, 95% CI [+0.152, +1.251] resampling cases, best deviation
    role 0 -- the actor -- to safety.  The interval clearing zero is the whole
    claim; the point estimate alone survived every budget while the equilibrium
    it implied did not.  Naming a *role* rather than a seat is what the role
    rebuild bought: under seat indexing the deviation was reported for seat 0,
    which is the actor in only half the corpus.

    DEV-179 moved the role back from 3 to 0 and roughly quadrupled the point
    estimate.  Attribution was measured, not guessed, by running this same
    budget on three trees: at 88cf44b (role 3, +0.153); with only the
    tsumogiri lock applied and the corpus untouched (role 0, +0.558); and with
    the re-seeded corpus on top (role 0, +0.611).  The role flip is therefore
    entirely the lock's doing, and the lock accounts for 89% of the movement in
    the point estimate.  This is the expected direction: a declared opponent
    that may only tsumogiri cannot fold, so the frozen seats stop competing for
    the safety gain and the actor becomes the role that profits most by taking
    it.  The old +0.153 was calibrated while rollout.py let declared opponents
    keep reshaping a hand the rules freeze, which is the defect DEV-179 fixed.

    Recorded 2026-08-25, before DEV-120: regret +0.259 tai, 95% CI
    [+0.100, +0.555], best deviation role 0 -- the actor -- to safety.  DEV-120
    replaced the uniform fill for non-tenpai opponents with the shanten
    distribution self-play observed, which moved 1- and 2-shanten opponents
    from 2.0% of sampled hands to 65.7%.  Which role gains most by folding is
    exactly the kind of thing a better opponent model is expected to move, so
    the role is re-baselined here rather than loosened away: it stays asserted,
    and the next time role attribution shifts this will say so again.
    """
    result = corpus_game.regret_interval(("efficiency",) * 4)
    assert result.resolved and result.low > 0.0, result
    assert (result.role, result.reply) == (0, "safety"), result


@pytest.mark.slow
def test_no_profile_in_this_abstraction_is_shown_to_be_an_equilibrium(corpus_game):
    """Guards the *negative* half of the step 3 writeup.

    Being an equilibrium means no deviation pays, which this budget can only
    show by putting the regret interval entirely below zero.  Rebuilding the
    game on roles did not change that: at 400 worlds no profile managed it and
    four stayed unresolved (`EESS`, `SEES`, `SESS`, `SSSS`), against five under
    seat indexing.  If one ever does, the "no equilibrium was solved" wording
    in docs/equilibrium-plan.md is stale and should fail here rather than
    quietly stay in the file.
    """
    solved = [
        profile for profile in corpus_game.payoffs
        if corpus_game.regret_interval(profile).high < 0.0
    ]
    assert not solved, solved
