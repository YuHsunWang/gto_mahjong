"""MJ-006 exact small-wall outcome and payment oracle."""

from fractions import Fraction

import pytest

from taimahjong.reference_ev import (
    OUTCOME_KINDS,
    compare_reference_corpus,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
    terminal_payment,
)
from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2


def test_exact_small_wall_probabilities_sum_to_one_and_cover_outcomes():
    state = standard_small_wall_state()
    evaluations = [
        evaluate_candidate(state, discard)
        for discard in state.legal_discards
    ]

    assert all(sum(item.probability for item in result.outcomes) == Fraction(1) for result in evaluations)
    observed = {
        item.outcome.kind
        for result in evaluations
        for item in result.outcomes
    }
    assert observed <= OUTCOME_KINDS
    assert {"self_tsumo", "self_ron", "opponent_ron", "opponent_tsumo", "draw"} <= observed


@pytest.mark.parametrize("scheme", [SCHEME_3_1, SCHEME_5_2])
@pytest.mark.parametrize(
    ("kind", "winner", "discarder"),
    [
        ("self_tsumo", 0, None),
        ("self_ron", 0, 2),
        ("opponent_ron", 2, 0),
        ("opponent_tsumo", 3, None),
        ("draw", None, None),
    ],
)
def test_every_terminal_payment_conserves_four_players(kind, winner, discarder, scheme):
    state = standard_small_wall_state()
    payment = terminal_payment(state, kind, winner, discarder, scheme)

    assert len(payment.deltas) == 4
    assert sum(payment.deltas) == 0
    if kind == "draw":
        assert payment.deltas == (0, 0, 0, 0)


def test_current_approximation_is_reported_against_reference_corpus():
    report = compare_reference_corpus(representative_reference_cases(), sims=8)

    assert report.cases >= 2
    assert report.candidate_comparisons >= report.cases * 2
    assert report.mean_absolute_ev_error >= 0
    assert 0 <= report.top1_agreement <= 1
    assert report.ranking_pairs > 0
    assert 0 <= report.ranking_inversion_rate <= 1
