"""Invariants for the shallow-endgame best response.

The information-set restriction cannot be checked by reading the number: a
plan that leaks hidden state reads *higher*, not wrong, so these tests pin the
structural properties that leakage would break.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import taimahjong.best_response as best_response
from taimahjong.best_response import (
    exploitability,
    observation_for,
    production_rank_policy,
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


@pytest.mark.slow
def test_measuring_the_best_response_against_itself_yields_zero():
    """Feeding the solved plan back in as the measured policy must close the
    gap exactly; any residue means the solver and the scorer disagree.

    Slow rather than fast only because it costs 9s of a 2.5-minute push
    budget: it solves twice per case. The four structural checks that stay in
    the fast batch cover non-negativity, the clairvoyant bound, the shape of
    the information key, and the zero end of the scale.
    """
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


def test_production_rank_policy_keeps_the_winning_branch_continuation(monkeypatch):
    """The root winner includes the fold entry, and a fold must keep defending
    from public counts that include every discard watched after the root."""
    observation = observation_for(DEEP_CASES[0])
    fold_tile, push_tile = tuple(
        tile for tile, count in enumerate(observation.hand) if count
    )[:2]
    captured = {}

    def fake_rank(*args, **kwargs):
        captured["rank_args"] = args
        captured["rank_kwargs"] = kwargs
        return [
            SimpleNamespace(discard=push_tile, net_ev=2.0, is_fold=False),
            SimpleNamespace(discard=fold_tile, net_ev=2.0, is_fold=True),
        ]

    def fake_fold(hand, visible, opponents, calibration, scheme):
        captured["fold"] = (hand, visible, opponents, calibration, scheme)
        return fold_tile

    monkeypatch.setattr(best_response, "ev_rank", fake_rank)
    monkeypatch.setattr(best_response, "_fold_choice", fake_fold)
    choice = production_rank_policy(
        observation, sims=7, seed=13,
    )
    assert choice.discard == fold_tile
    assert choice.is_fold
    assert captured["rank_args"] == (
        observation.hand, observation.views, observation.visible,
    )
    assert captured["rank_kwargs"]["turns"] == 1
    assert "rollout_players" not in captured["rank_kwargs"]
    assert "rollout_wall" not in captured["rank_kwargs"]

    watched_tile = next(
        tile
        for tile, remaining in enumerate(observation.belief_remaining())
        if remaining
    )
    remaining = observation.belief_remaining(
        observation.hand,
        ((observation.next_seat, watched_tile),),
    )
    assert choice.continuation(observation.hand, remaining, 0) == fold_tile
    reconstructed = captured["fold"][1]
    assert reconstructed == tuple(
        4 - observation.hand[tile] - remaining[tile]
        for tile in range(34)
    )
    assert reconstructed[watched_tile] == observation.visible[watched_tile] + 1


def test_measured_opening_can_use_a_policy_continuation_without_a_plan():
    """A root-only rank choice intentionally falls back to its branch policy
    at every later information set it does not provide as a solved plan."""
    case = SPANNING_CASES[0]
    opening = case.state.legal_discards[0]
    result = exploitability(
        case,
        sims=1,
        seed=1,
        mode="opening",
        measured_opening=opening,
    )
    assert result.production_discard == opening


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
    """The headline measurement, at a budget worth quoting.

    DEV-179 moved this band.  Locking declared opponents to tsumogiri is the
    correct table rule, and it roughly doubled measured exploitability: the
    corpus mean went 0.620 -> 1.204 tai, past the old 1.2 ceiling.  The ceiling
    is raised to 1.5 rather than the measurement being explained away, because
    the old ceiling was calibrated while rollout.py still let declared
    opponents reshape a frozen hand.

    The rise was attributed per case, not assumed: every case without a
    declared opponent stayed at zero, and the gap increased with declared
    exposure.  The group sizes are 11/5/4/6.  The later DEV-184 attribution at
    the same 60-world, seed-1 budget shows why the simple measured rule is a
    strawman: ``_production_discard_policy`` is pure ukeire and danger-blind,
    while production's root rank can choose a separately priced fold branch.

        declared  n   pure-ukeire   pure-defensive   defensive-iff-declared
               0  11       0.0000           2.4427                   0.0000
               1   5       0.6528           0.2328                   0.2328
               2   4       2.5965           0.9583                   0.9583
               3   6       2.9424           0.7875                   0.7875
             ALL  26       1.2040           1.4074                   0.3739

    Thus DEV-179's lock enlarged a gap that already existed rather than
    creating one.  What it enlarged, though, was the gap of a policy production
    never plays.  Measuring the real root choice and its own continuation, at
    the same budget (``scripts/production_rank_exploitability.py``):

        declared  n   opening   clairvoyant
               0  11    0.1364        0.1417
               1   5    0.2361        0.3056
               2   4    0.0000        0.0000
               3   6    1.1278        1.2792
             ALL  26    0.3634        0.4139

    The rank picks the fold branch in 11 of the 15 cases that face a declared
    opponent, and 22 of the 26 cases come out at exactly zero.  Two facts say
    the rank is doing more than adding a fold button.  Its push branch also
    picks better tiles: ``deal-in-2-shanten-nondealer-...-threat-multiple`` was
    the corpus's worst case under both fixed rules (3.85 and 3.83) and is zero
    once the rank chooses the discard.  And what is left is not spread thin --
    ``deal-in-2-shanten-dealer-streak2-5-2-shallow-1-threat-multiple`` alone
    contributes 6.7667/26 = 0.260 tai, 72% of the whole remaining mean, by
    pushing a root that should have folded.  That single case, not the corpus
    average, is where any further work belongs.

    Recorded 2026-08-24: 0.556 and 0.898 tai.  Re-measured against the ukeire
    strawman 2026-09-05: 1.204 and 1.762.  Against production's actual root
    rank 2026-09-06: 0.363 and 0.414.
    """
    measured = [
        production_rank_policy(observation_for(case), sims=60, seed=1)
        for case in CASES
    ]
    constrained = [
        exploitability(
            case,
            sims=60,
            seed=1,
            mode="opening",
            measured_opening=choice.discard,
            measured_policy=choice.continuation,
        )
        for case, choice in zip(CASES, measured)
    ]
    for result in constrained:
        assert result.exploitability >= 0.0, result.name
    free = [
        exploitability(
            case,
            sims=60,
            seed=1,
            mode="clairvoyant",
            measured_opening=choice.discard,
            measured_policy=choice.continuation,
        )
        for case, choice in zip(CASES, measured)
    ]
    for tight, loose in zip(constrained, free):
        assert loose.exploitability >= tight.exploitability - 1e-9
    mean_constrained = sum(r.exploitability for r in constrained) / len(constrained)
    mean_free = sum(r.exploitability for r in free) / len(free)
    # The band pins the order of magnitude, not the point estimate, and keeps
    # roughly the 2x headroom the pre-DEV-179 ceiling had over its own
    # measurement.  DEV-179 raised this to 1.5 over a strawman policy; DEV-184
    # measures production's real choice and brings it back below the 1.2 that
    # stood before.  A floor still catches a harness that silently reports zero.
    assert 0.1 <= mean_constrained <= 0.8
    assert mean_constrained <= mean_free <= 1.0
