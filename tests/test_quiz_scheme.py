"""Teaching thresholds measure comparable losses across payout schemes."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from server import api
from taimahjong import quiz, trainer
from taimahjong.analysis import AnalysisContext
from taimahjong.config import GameConfig
from taimahjong.moments import SampleMoments
from taimahjong.scoring import DEFAULT_SCHEME, SCHEME_3_1, SCHEME_5_2


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (-0.000001, "best"), (0.0, "best"), (0.000001, "good"),
        (0.299999, "good"), (0.3, "inaccuracy"), (0.300001, "inaccuracy"),
        (0.999999, "inaccuracy"), (1.0, "mistake"), (1.000001, "mistake"),
    ],
)
def test_scheme_preserves_verdict_near_every_boundary(delta, expected):
    # Explicit expected labels lock the original default-scheme behavior.
    assert quiz.verdict_for_delta(delta) == expected
    for scheme in (SCHEME_3_1, SCHEME_5_2):
        factor = scheme.value(1) / DEFAULT_SCHEME.value(1)
        assert quiz.verdict_for_delta(delta * factor, scheme) == expected
        assert quiz.threshold_gap(delta * factor, scheme) == pytest.approx(
            quiz.threshold_gap(delta) * factor,
        )


@pytest.mark.parametrize("boundary", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("band", [quiz.ESCALATE_MARGIN, quiz.MARGINAL_BAND])
@pytest.mark.parametrize("offset", [-0.000001, 0.000001])
def test_adaptive_budget_and_marginality_scale_with_scheme(boundary, band, offset):
    delta = boundary + band + offset
    outcomes = []
    for scheme in (SCHEME_3_1, SCHEME_5_2):
        factor = scheme.value(1) / DEFAULT_SCHEME.value(1)
        budgets = []

        def estimate(sims):
            budgets.append(sims)
            return delta * factor, sims

        outcome, payload = quiz.resolve_adaptive(estimate, 1, scheme)
        assert payload == outcome.refined_sims
        assert not quiz.should_escalate(delta * factor, 2, scheme)
        outcomes.append((outcome.verdict, outcome.refined_sims, outcome.marginal, budgets))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][1] == (
        quiz.ESCALATE_SIMS
        if quiz.threshold_gap(delta) < quiz.ESCALATE_MARGIN
        else quiz.REFINE_SIMS
    )
    assert outcomes[0][2] == (quiz.threshold_gap(delta) < quiz.MARGINAL_BAND)


@pytest.mark.parametrize("delta", [0.099999, 0.1, 0.100001])
def test_ranking_effect_band_and_api_payload_scale(delta, monkeypatch):
    states = []
    for scheme in (SCHEME_3_1, SCHEME_5_2):
        factor = scheme.value(1) / DEFAULT_SCHEME.value(1)
        moments = SampleMoments.from_values([delta * factor] * 2)
        result = quiz.QuizGrade(
            None, None, None, (), 0.0, 1, "best", top_gap=moments, scheme=scheme,
        )
        states.append(result.ranking_state)
        monkeypatch.setattr(api, "paired_delta_moments", lambda *args: moments)
        entries = [
            api.EVRankEntry(0, 0.0, None, 1.0, (), 0.0, 1.0),
            api.EVRankEntry(1, 0.0, None, 0.0, (), 0.0, 0.0),
        ]
        payload = api._top_gap_payload(entries, scheme)
        assert payload["effect_threshold"] == pytest.approx(0.1 * factor)
        # Grade serialization must use the scheme retained by the engine.
        monkeypatch.setattr(api, "explain", lambda result: "")
        monkeypatch.setattr(api, "_mistake_label_payload", lambda result: None)
        assert api._grade_payload(replace(result, best=entries[0], chosen=entries[0], ranked=tuple(entries)))["top1_vs_top2"] == payload
    assert states == ["marginal" if delta < 0.1 else "clear"] * 2


@pytest.mark.parametrize("evaluation_type", [trainer.CallEvaluation, trainer.KongEvaluation])
def test_trainer_passes_scheme_to_shared_adaptive_grader(evaluation_type, monkeypatch):
    monkeypatch.setattr(evaluation_type, "_action_ev", lambda self, choice, sims: 0.2)
    monkeypatch.setattr(evaluation_type, "_action_shanten", lambda self, choice: 2)
    evaluation = evaluation_type(
        pass_ev=0.0, option_evs=(0.7,), best_index=0, best_ev=0.7,
        best_ev_sims=quiz.REFINE_SIMS, decision=None, scheme=SCHEME_5_2,
    )
    # A 0.5-chip loss is good at 5/2 (boundary 0.525), inaccurate at default.
    result = evaluation.verdict_for(None)
    assert result.verdict == "good"
    assert result.marginal


@pytest.mark.parametrize("endpoint", [api.quiz_grade, api.endgame_grade])
def test_quiz_and_endgame_grade_use_scheme_from_analysis(endpoint, monkeypatch):
    position = SimpleNamespace(hand=(1, 1) + (0,) * 32, own_melds=(), own_kongs=())
    entries = [
        api.EVRankEntry(0, 0.0, None, 0.7, (), 0.0, 0.7),
        api.EVRankEntry(1, 0.0, None, 0.2, (), 0.0, 0.2),
    ]
    monkeypatch.setattr(quiz, "_full_rank", lambda position, analysis: entries)
    monkeypatch.setattr(quiz, "_cached_shanten", lambda *args: 2)
    monkeypatch.setattr(api, "_quiz_position", lambda *args: position)
    monkeypatch.setattr(api, "_endgame_position", lambda *args: SimpleNamespace(position=position, tag="attack"))
    monkeypatch.setattr(api, "_grade_payload", lambda result: {
        "verdict": result.verdict, "scheme": result.scheme,
    })
    context = AnalysisContext(GameConfig(SCHEME_5_2))
    result = quiz.grade(position, 1, analysis=context)
    assert result.verdict == "good"
    assert result.scheme == SCHEME_5_2
    assert result.marginal
    payload = endpoint(api.GradeRequest(seed=1, tile=1, scheme="5-2"))
    assert payload["grade"] == {"verdict": "good", "scheme": SCHEME_5_2}
