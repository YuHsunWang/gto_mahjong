"""MJ-006 exact small-wall outcome and payment oracle."""

from dataclasses import replace
from fractions import Fraction

import pytest

from taimahjong.config import DEFAULT_RULES
from taimahjong.reference_ev import (
    OUTCOME_KINDS,
    compare_reference_corpus,
    corpus_gate,
    evaluate_candidate,
    representative_reference_cases,
    standard_small_wall_state,
    terminal_payment,
)
from taimahjong.scoring import SCHEME_3_1, SCHEME_5_2
from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles


@pytest.fixture(scope="module")
def corpus_comparison():
    return compare_reference_corpus(representative_reference_cases())


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


def test_oracle_multi_ron_policy_changes_terminal_and_conserves_payments():
    state = standard_small_wall_state(wall=())
    players = list(state.players)
    players[2] = replace(
        players[2],
        hand=parse_tiles("123456m123p123s333z6z"),
    )
    state = replace(state, players=tuple(players))
    discard = next(
        tile for tile, count in enumerate(parse_tiles("6z")) if count
    )
    all_rules = replace(
        DEFAULT_RULES, rules_id="taiwanese-multi-ron-v1", multi_ron="all",
    )

    nearest = evaluate_candidate(state, discard, DEFAULT_RULES)
    multi = evaluate_candidate(state, discard, all_rules)
    nearest_outcome = nearest.outcomes[0].outcome
    multi_outcome = multi.outcomes[0].outcome

    assert nearest_outcome.ron_winners == (1,)
    assert multi_outcome.ron_winners == (1, 2)
    assert sum(nearest_outcome.payment.deltas) == 0
    assert sum(multi_outcome.payment.deltas) == 0
    assert nearest_outcome.payment.deltas[2] == 0
    assert multi_outcome.payment.deltas[1] > 0
    assert multi_outcome.payment.deltas[2] > 0
    assert multi_outcome.payment.deltas[0] < nearest_outcome.payment.deltas[0]


def test_reference_corpus_is_stratified_and_branch_dominant():
    cases = representative_reference_cases()
    probabilistic_cases = 0
    observed_kinds = set()

    assert len(cases) == 26
    assert {case.strata.actor_role for case in cases} == {"dealer", "nondealer"}
    assert {case.strata.dealer_streak for case in cases} == {0, 2}
    assert {case.strata.scheme for case in cases} == {"3-1", "5-2"}
    assert {case.strata.wall_depth for case in cases} == {
        "shallow-1", "short-2", "medium-3", "deep-4",
    }
    assert {case.strata.hand_state for case in cases} == {
        "tenpai", "1-shanten", "2-shanten",
    }
    assert {case.strata.threat_level for case in cases} == {
        "none", "one", "multiple",
    }
    assert {case.strata.branch_character for case in cases} == {
        "draw", "deal-in", "actor-tsumo", "self-ron", "opponent-ron",
        "opponent-tsumo",
    }
    for case in cases:
        actor = case.state.players[case.state.acting_seat]
        assert shanten(actor.hand) == {
            "tenpai": 0,
            "1-shanten": 1,
            "2-shanten": 2,
        }[case.strata.hand_state]
        evaluations = [
            evaluate_candidate(case.state, discard)
            for discard in case.state.legal_discards
        ]
        exact_best = max(
            evaluations,
            key=lambda result: (result.actor_ev, -result.discard),
        )
        kind_probabilities = {
            kind: sum(
                outcome.probability
                for outcome in exact_best.outcomes
                if outcome.outcome.kind == kind
            )
            for kind in {outcome.outcome.kind for outcome in exact_best.outcomes}
        }
        expected_kind = {
            "draw": "draw",
            "deal-in": "opponent_ron",
            "actor-tsumo": "self_tsumo",
            "self-ron": "self_ron",
            "opponent-ron": "opponent_ron",
            "opponent-tsumo": "opponent_tsumo",
        }[case.strata.branch_character]
        observed_kinds.update(kind_probabilities)
        expected_probability = kind_probabilities[expected_kind]
        assert expected_probability == max(kind_probabilities.values())
        assert list(kind_probabilities.values()).count(expected_probability) == 1
        probabilistic_cases += len(kind_probabilities) > 1

    assert observed_kinds == OUTCOME_KINDS
    assert probabilistic_cases >= 8


def test_current_approximation_is_reported_against_reference_corpus(
    corpus_comparison,
):
    report = corpus_comparison

    assert report.cases == 26
    assert report.candidate_comparisons >= report.cases * 2
    assert report.mean_absolute_ev_error >= 0
    assert 0 <= report.top1_agreement <= 1
    assert report.ranking_pairs > 0
    assert 0 <= report.ranking_inversion_rate <= 1
    assert report.mean_top1_regret >= 0
    assert report.max_top1_regret >= report.mean_top1_regret
    assert -1 <= report.rank_correlation <= 1
    assert len(report.case_results) == report.cases
    assert all(result.top1_regret >= 0 for result in report.case_results)
    assert all(
        -1 <= result.rank_correlation <= 1
        for result in report.case_results
    )


def test_reference_corpus_gate_can_accept_a_conforming_comparison(
    corpus_comparison,
):
    conforming = replace(
        corpus_comparison,
        mean_absolute_ev_error=0.0,
        top1_agreement=1.0,
        ranking_inversion_rate=0.0,
        mean_top1_regret=0.0,
        max_top1_regret=0.0,
        rank_correlation=1.0,
    )

    assert corpus_gate(conforming).passed


@pytest.mark.parametrize("seed_offset", [0, 1000])
def test_production_ev_rank_passes_reference_corpus_gate(
    corpus_comparison,
    seed_offset,
):
    comparison = (
        corpus_comparison
        if seed_offset == 0
        else compare_reference_corpus(
            representative_reference_cases(),
            seed_offset=seed_offset,
        )
    )
    result = corpus_gate(comparison)

    assert result.passed, "; ".join(result.failures)
