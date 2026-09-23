"""Structural invariants for the empirical game's own 416-case corpus.

These pin the corpus's shape, not any conclusion drawn from it: the
conclusions stay pinned to the 26-case acceptance corpus in
``tests/test_empirical_game.py``, which is deliberately not built from this
module.  What can silently rot here is the balance -- a corpus that drifted
into, say, 40 dealer cases would quietly change what the reported averages
mean -- and the separation from the acceptance corpus, which is the whole
reason this module exists.
"""

from __future__ import annotations

from collections import Counter

import pytest

from taimahjong.best_response import observation_for
from taimahjong.empirical_corpus import actor_hands, empirical_game_cases
from taimahjong.empirical_game import build_game, profile_payoffs
from taimahjong.best_response import sample_worlds
from taimahjong.reference_ev import MIN_GATE_CASES, representative_reference_cases
from taimahjong.shanten import shanten


CASES = empirical_game_cases()
STEP_3C = empirical_game_cases(13)
STEP_3D = empirical_game_cases(26)


def test_the_acceptance_corpus_is_untouched():
    """The gate four other test modules depend on must not move because the
    empirical game wanted more cases; that separation is why this corpus
    exists at all."""
    assert MIN_GATE_CASES == 26
    assert len(representative_reference_cases()) == 26


def test_every_hand_appears_once_at_each_wall_depth():
    """Wall depth decides which roles get to act, so it must not be
    confounded with the hand: a depth effect read off a corpus where the deep
    cases also hold the harder hands is not a depth effect."""
    seen = Counter(
        (case.strata.hand_state, case.name.rsplit("-threat-", 1)[0])
        for case in CASES
    )
    assert len(actor_hands()) == 104
    assert len(CASES) == 416
    assert Counter(len(case.state.wall) for case in CASES) == {
        1: 104, 2: 104, 3: 104, 4: 104,
    }
    assert all(count == 1 for count in seen.values())


def test_the_reported_averages_are_over_a_balanced_corpus():
    """Every average this corpus feeds is an average over its own strata, so
    an imbalance is a silent reweighting of the claim."""
    for cases, half in ((CASES, 208), (STEP_3D, 52), (STEP_3C, 26)):
        assert Counter(case.state.acting_seat for case in cases) == {0: half, 1: half}
        assert Counter(case.state.dealer_streak for case in cases) == {0: half, 2: half}
        assert Counter(case.strata.scheme for case in cases) == {
            "3-1": half, "5-2": half,
        }
        assert Counter(
            sum(1 for player in case.state.players if player.declared_at is not None)
            for case in cases
        ) == {0: half // 2, 1: half // 2, 2: half // 2, 3: half // 2}


def test_the_earlier_corpora_stay_reproducible():
    """The published tables were measured at 52 and 104 cases.  If growing the
    corpus reordered or renumbered those, the tables would no longer be
    reproducible from this code and could not be compared against."""
    assert len(STEP_3C) == 52
    assert len(STEP_3D) == 104
    for earlier in (STEP_3C, STEP_3D):
        for small, full in zip(earlier, CASES):
            assert small.name == full.name
            assert small.seed == full.seed
            assert small.state == full.state


def test_truncating_off_a_block_boundary_is_refused():
    """Each block of thirteen templates balances on its own, so a truncation
    anywhere else silently returns an unbalanced corpus; refuse instead."""
    with pytest.raises(ValueError):
        empirical_game_cases(20)


def test_every_actor_hand_matches_its_declared_shanten():
    """The stratum label is used to read the tables, so a hand that drifted
    out of its stratum would mislabel a whole row."""
    wanted = {"tenpai": 0, "1-shanten": 1, "2-shanten": 2}
    for case in CASES:
        hand = case.state.players[case.state.acting_seat].hand
        assert sum(hand) == 17, case.name
        assert shanten(hand) == wanted[case.strata.hand_state], case.name


def test_the_filler_opponents_are_never_read_by_the_empirical_game():
    """The corpus's opponent hands are filler.  If the empirical game ever
    started reading them, this corpus would be silently wrong -- so pin the
    fact that only the actor's view crosses the boundary."""
    case = CASES[0]
    observation = observation_for(case)
    assert observation.hand == case.state.players[case.state.acting_seat].hand
    assert observation.wall_size == len(case.state.wall)
    worlds = sample_worlds(observation, 2, 5)
    for world in worlds:
        for seat in range(4):
            if seat == case.state.acting_seat:
                continue
            assert world.players[seat].hand != case.state.players[seat].hand


def test_a_role_the_wall_never_reaches_gains_exactly_zero():
    """After the actor discards, the remaining ``d`` draws go to roles 1, 2,
    3, 1.  A role that never draws cannot change any payoff, and the gain has
    to be zero exactly, not approximately -- the per-world expectation is
    exact rational arithmetic."""
    case = next(case for case in CASES if len(case.state.wall) == 1)
    observation = observation_for(case)
    world = sample_worlds(observation, 1, 5)[0]
    base = profile_payoffs(world, observation, ("efficiency",) * 4)
    for role in (2, 3):
        tilted = list(("efficiency",) * 4)
        tilted[role] = "safety"
        assert profile_payoffs(
            world, observation, tuple(tilted),
        ) == base, role


def test_the_corpus_game_settles_zero_sum():
    """Settlement moves value between seats and never creates it; a profile
    whose payoffs do not cancel means the tabulation is wrong."""
    game = build_game(CASES[:4], sims=2, seed=1)
    for profile, payoffs in game.payoffs.items():
        assert sum(payoffs) == pytest.approx(0.0, abs=1e-9), profile
