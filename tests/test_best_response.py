"""Invariants for the shallow-endgame best response.

The information-set restriction cannot be checked by reading the number: a
plan that leaks hidden state reads *higher*, not wrong, so these tests pin the
structural properties that leakage would break.
"""

from __future__ import annotations

import pytest

from taimahjong.best_response import (
    exploitability,
    observation_for,
    sample_worlds,
    _analyse_opening,
)
from taimahjong.config import DEFAULT_RULES
from taimahjong.reference_ev import representative_reference_cases


CASES = representative_reference_cases()
DEEP_CASES = tuple(case for case in CASES if len(case.state.wall) == 4)
# One case per wall depth keeps the push-time subset honest without paying for
# the whole corpus; the slow test below sweeps all 26.
SPANNING_CASES = tuple(
    next(case for case in CASES if len(case.state.wall) == depth)
    for depth in (1, 2, 3, 4)
)


def test_exploitability_is_never_negative():
    """The best response can always copy the measured policy, so a negative
    gap means the two are not being scored on the same information."""
    for case in SPANNING_CASES:
        result = exploitability(case, sims=8, seed=1, mode="opening")
        assert result.exploitability >= 0.0, case.name


def test_measuring_the_best_response_against_itself_yields_zero():
    """Feeding the solved plan back in as the measured policy must close the
    gap exactly; any residue means the solver and the scorer disagree."""
    for case in DEEP_CASES[:2]:
        solved = exploitability(case, sims=8, seed=1, mode="opening")
        again = exploitability(
            case,
            sims=8,
            seed=1,
            mode="opening",
            measured_opening=solved.best_response_discard,
            measured_plan=solved.plan,
        )
        assert again.exploitability == pytest.approx(0.0, abs=1e-12), case.name


def test_clairvoyant_bounds_the_information_set_answer():
    """Dropping the information-set constraint can only help the best
    response, so it must never come out below the constrained answer."""
    for case in DEEP_CASES[:2]:
        constrained = exploitability(case, sims=8, seed=1, mode="opening")
        free = exploitability(case, sims=8, seed=1, mode="clairvoyant")
        assert free.exploitability >= constrained.exploitability - 1e-9, case.name


def test_actor_information_key_excludes_hidden_state():
    """The key must be exactly (own hand, watched discards).

    Two worlds that differ only in hidden state the actor never observes must
    land on the same information set; if opponent hands or wall contents leaked
    into the key they could not.
    """
    case = DEEP_CASES[0]
    observation = observation_for(case)
    worlds = sample_worlds(observation, 6, 11)
    discard = case.state.legal_discards[0]
    for world in worlds:
        _, contributions = _analyse_opening(
            world, observation, discard, DEFAULT_RULES,
        )
        for hand, observed in contributions:
            assert sum(hand) == 17
            # Watched discards carry a seat and a tile, and never the actor's.
            for seat, tile in observed:
                assert seat != observation.acting_seat
                assert 0 <= tile < 34


@pytest.mark.slow
def test_full_mode_information_sets_are_effectively_singletons():
    """Documents why "full" is not reported as exploitability.

    The acting seat watches its own draw and three opponent discards, so its
    depth-two information sets almost never collide across sampled worlds and
    the solved plan overfits the world it was fitted on.
    """
    case = DEEP_CASES[1]
    result = exploitability(case, sims=40, seed=1, mode="full")
    assert result.information_sets > 0
    assert result.shared_information_sets / result.information_sets < 0.05
    free = exploitability(case, sims=40, seed=1, mode="clairvoyant")
    assert result.exploitability == pytest.approx(free.exploitability, abs=1e-9)


def test_a_tenpai_actor_that_tsumos_has_nothing_left_on_the_table():
    """A hand already committed to its winning wait cannot be improved, so
    these cases pin the zero end of the scale."""
    for case in CASES:
        if not case.name.startswith("actor-tsumo-"):
            continue
        result = exploitability(case, sims=4, seed=1, mode="opening")
        assert result.exploitability == pytest.approx(0.0, abs=1e-12), case.name


@pytest.mark.slow
def test_corpus_exploitability_at_a_reportable_budget():
    """The headline measurement, at a budget worth quoting."""
    constrained = [
        exploitability(case, sims=60, seed=1, mode="opening")
        for case in CASES
    ]
    for result in constrained:
        assert result.exploitability >= 0.0, result.name
    free = [
        exploitability(case, sims=60, seed=1, mode="clairvoyant")
        for case in CASES
    ]
    for tight, loose in zip(constrained, free):
        assert loose.exploitability >= tight.exploitability - 1e-9
    mean_constrained = sum(r.exploitability for r in constrained) / len(constrained)
    mean_free = sum(r.exploitability for r in free) / len(free)
    # Recorded 2026-08-24: 0.556 and 0.898 tai.  The band is wide because this
    # pins the order of magnitude, not the point estimate.
    assert 0.2 <= mean_constrained <= 1.2
    assert mean_constrained <= mean_free <= 2.0
