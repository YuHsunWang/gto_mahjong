"""MJ-004 calibration identity, fallback, and composition-root wiring."""

from dataclasses import dataclass

import pytest

from server import api
from taimahjong import quiz
from taimahjong.analysis import AnalysisContext, CalibrationContext, CalibrationProvider
from taimahjong.config import DEFAULT_GAME_CONFIG
from taimahjong.trainer import TrainerDecision


@dataclass(frozen=True)
class _ExtremeCalibration:
    probability: float

    def deal_in_probability(self, danger_score: float) -> float:
        return self.probability


def _context(identity: str, probability: float) -> AnalysisContext:
    return AnalysisContext(
        DEFAULT_GAME_CONFIG,
        CalibrationContext(identity, _ExtremeCalibration(probability)),
    )


def _real_entry(payload, discard):
    return next(
        entry for entry in payload["entries"]
        if not entry["is_fold"] and entry["discard"] == discard
    )


# DEV-207: one quiz grade is one Monte Carlo draw at one fixed seed. Measured on
# this test's position and discard over 20 seeds at REFINE_SIMS=200, raising the
# deal-in probability 200x raised risk_ev by +0.40 on average (sd 0.26) but went
# the other way at 2 of the 20 seeds -- and the seed this test used to rely on
# is one of them (4.129 -> 4.022). Raising sims does not help: at 1000 sims the
# spread only fell to 0.20, and at that seed net_ev turned wrong instead. The
# noise is between seeds, so the direction is checked on a seed average.
QUIZ_DIRECTION_SEEDS = 8


def _seed_averaged_quiz_chosen(monkeypatch, position, tile, analysis):
    """Mean (risk_ev, net_ev) of the quiz's own chosen-discard estimate over seeds."""
    original = quiz._evaluation_seed
    risk, net = [], []
    for offset in range(QUIZ_DIRECTION_SEEDS):
        monkeypatch.setattr(
            quiz, "_evaluation_seed",
            lambda pos, offset=offset: original(pos) + offset,
        )
        entry = quiz._refine(position, tile, quiz.REFINE_SIMS, analysis=analysis)
        risk.append(entry.risk_ev)
        net.append(entry.net_ev)
    monkeypatch.setattr(quiz, "_evaluation_seed", original)
    return sum(risk) / len(risk), sum(net) / len(net)


# Drives quiz and trainer end-to-end twice, plus an 8-seed quiz average (~2 min).
@pytest.mark.slow
def test_extreme_calibration_moves_stateless_quiz_and_trainer_risk_together(monkeypatch):
    # risk_ev and net_ev are sample means over terminal rollouts (ev.py:895),
    # so comparing two calibrations compares two expectations and needs enough
    # trials for the difference to clear the sampling noise. Swept on this exact
    # position against the current model, low/high risk_ev runs:
    #
    #      50   2.8800 / 2.8800   <- exact tie, a knife edge
    #     100   2.9800 / 3.1700
    #     150   3.0267 / 3.5333
    #     200   3.1600 / 3.8250
    #     300   3.0300 / 3.7467
    #
    # The separation grows with samples and settles near 0.7, so 200 sits on a
    # plateau rather than on the edge that 50 turned out to be. net_ev separates
    # at every size tested, including 50. Do not lower these back.
    monkeypatch.setattr(quiz, "EV_SIMS", 2)
    monkeypatch.setattr(quiz, "REFINE_SIMS", 200)
    monkeypatch.setattr(quiz, "ESCALATE_SIMS", 201)
    quiz._rank_cached.cache_clear()
    api._SESSIONS.clear()
    low_context = _context("extreme-low", 0.001)
    high_context = _context("extreme-high", 0.20)
    active = [low_context]
    monkeypatch.setattr(api, "_calibration_context", lambda: active[0].calibration)

    # A real trainer decision supplies one fixed observable position to both
    # quiz grading and the trainer session path.
    low_state = api.trainer_new(api.TrainerNewRequest(seed=1, scheme="3-1"))
    low_session = api._SESSIONS[low_state["session_id"]]
    assert isinstance(low_session.current, TrainerDecision)
    position = low_session.current.position
    tile = next(index for index, count in enumerate(position.hand) if count)
    monkeypatch.setattr(api, "_quiz_position", lambda seed, analysis: position)

    low_quiz = api.quiz_grade(api.GradeRequest(seed=1, tile=tile, scheme="3-1"))
    low_trainer = api.trainer_act(
        low_state["session_id"],
        api.TrainerActRequest(
            step=low_state["step"], action="discard", tile=tile, scheme="3-1",
        ),
    )
    # Both stateless runs must be exhaustive. The screener keeps whichever
    # candidates could still be best *under that calibration*, so a 200x swing
    # in deal-in probability legitimately returns different top-k sets — low
    # keeps 19/18/20/9/2/0 and high keeps 11/1/10/9/0. Comparing one discard
    # across the two runs then depends on the sets happening to overlap, which
    # is not the property under test. Over the full legal set the comparison is
    # always well defined.
    stateless_request = dict(
        hand="123m123p123s11122233z",
        river="9m9p1z",
        turns=1,
        sims=50,
        seed=17,
        scheme="3-1",
        exhaustive=True,
    )
    low_stateless = api.ev_rank_endpoint(api.EvRankRequest(**stateless_request))
    stateless_discard = next(
        entry["discard"] for entry in low_stateless["entries"] if not entry["is_fold"]
    )

    active[0] = high_context
    high_state = api.trainer_new(api.TrainerNewRequest(seed=1, scheme="3-1"))
    high_quiz = api.quiz_grade(api.GradeRequest(seed=1, tile=tile, scheme="3-1"))
    high_trainer = api.trainer_act(
        high_state["session_id"],
        api.TrainerActRequest(
            step=high_state["step"], action="discard", tile=tile, scheme="3-1",
        ),
    )
    high_stateless = api.ev_rank_endpoint(api.EvRankRequest(**stateless_request))

    low_quiz_risk, low_quiz_net = _seed_averaged_quiz_chosen(monkeypatch, position, tile, low_context)
    high_quiz_risk, high_quiz_net = _seed_averaged_quiz_chosen(monkeypatch, position, tile, high_context)
    assert high_quiz_risk > low_quiz_risk
    # The trainer grades a discard through the same grade() on the same position
    # and seed, so its numbers carry the same seed noise as one quiz grade. What
    # the trainer path must prove is wiring: under each calibration it returns
    # exactly what the quiz does, and the quiz direction is checked above.
    for trainer, quiz_payload in ((low_trainer, low_quiz), (high_trainer, high_quiz)):
        for field in ("risk_ev", "net_ev"):
            assert trainer["feedback"]["chosen"][field] == quiz_payload["grade"]["chosen"][field]
    assert high_quiz["grade"]["chosen"]["risk_ev"] != low_quiz["grade"]["chosen"]["risk_ev"]
    assert (
        _real_entry(high_stateless, stateless_discard)["risk_ev"]
        > _real_entry(low_stateless, stateless_discard)["risk_ev"]
    )

    # net_ev is the more robust witness of the same property. risk_ev sees only
    # the loss side, and a calibrated ron ENDS the hand, so raising deal-in
    # probability truncates future losses and future gains together and moves
    # risk_ev less than the change in probability would suggest -- 3.160 to
    # 3.825 at 200 trials for a 200x change. net_ev separates far more widely
    # over the same span, -2.245 to -3.825, and separated at every sample size
    # tested including the one where risk_ev tied.
    # More deal-in risk must never make a decision look better.
    assert high_quiz_net < low_quiz_net
    assert (
        _real_entry(high_stateless, stateless_discard)["net_ev"]
        < _real_entry(low_stateless, stateless_discard)["net_ev"]
    )
    assert high_quiz["calibration_id"] == high_trainer["calibration_id"] == "extreme-high"
    assert high_stateless["calibration_id"] == "extreme-high"


def test_calibration_hash_is_in_quiz_cache_key_and_same_hash_reproduces(monkeypatch):
    # ``_rank`` is the displayed ranking and is keyed through
    # ``_display_rank_cached`` at REFINE_SIMS; ``_rank_cached`` now only backs
    # ``_screen_rank``. Watch the cache this call actually consults.
    monkeypatch.setattr(quiz, "EV_SIMS", 2)
    monkeypatch.setattr(quiz, "REFINE_SIMS", 2)
    quiz._display_rank_cached.cache_clear()
    position = next(api.play_trainer(1)).position
    first = _context("hash-a", 0.01)
    second = _context("hash-b", 0.20)

    ranked_a = quiz._rank(position, analysis=first)
    after_a = quiz._display_rank_cached.cache_info()
    assert quiz._rank(position, analysis=first) == ranked_a
    after_repeat = quiz._display_rank_cached.cache_info()
    quiz._rank(position, analysis=second)
    after_b = quiz._display_rank_cached.cache_info()

    assert after_repeat.hits == after_a.hits + 1
    assert after_b.misses == after_repeat.misses + 1


def test_missing_table_falls_back_consistently_and_responses_say_so(tmp_path, monkeypatch):
    fallback = CalibrationProvider(tmp_path / "missing.json").load()
    assert fallback.fallback_used and fallback.calibration_id == "heuristic-fallback"
    monkeypatch.setattr(api, "_calibration_context", lambda: fallback)
    monkeypatch.setattr(quiz, "EV_SIMS", 1)
    monkeypatch.setattr(quiz, "REFINE_SIMS", 2)
    monkeypatch.setattr(quiz, "ESCALATE_SIMS", 3)
    api._SESSIONS.clear()

    trainer = api.trainer_new(api.TrainerNewRequest(seed=1))
    position = api._SESSIONS[trainer["session_id"]].current.position
    tile = next(index for index, count in enumerate(position.hand) if count)
    trainer_grade = api.trainer_act(
        trainer["session_id"],
        api.TrainerActRequest(
            step=trainer["step"], action="discard", tile=tile,
        ),
    )
    monkeypatch.setattr(api, "_quiz_position", lambda seed, analysis: position)
    quiz_response = api.quiz_grade(api.GradeRequest(seed=1, tile=tile))
    stateless = api.ev_rank_endpoint(api.EvRankRequest(
        hand="123m123p123s11122233z", river="9m", turns=1, sims=1,
    ))

    for response in (trainer_grade, quiz_response, stateless):
        assert response["calibration_id"] == "heuristic-fallback"
        assert response["domain"] == "bot"
        assert response["fallback_used"] is True


@pytest.mark.parametrize("content", [
    "{truncated",
    '{"metadata":{"danger_binning":{"edges":[0,1],"buckets":["a"]}}}',
    "[]",
    '{"counts": null}',
])
def test_malformed_table_warns_and_uses_heuristic_fallback(tmp_path, caplog, content):
    path = tmp_path / "calibration.json"
    path.write_text(content, encoding="utf-8")

    with caplog.at_level("WARNING"):
        fallback = CalibrationProvider(path).load()

    assert fallback.fallback_used
    assert fallback.calibration_id == "heuristic-fallback"
    assert "unusable calibration table" in caplog.text


def test_malformed_table_api_reports_fallback(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    path = tmp_path / "calibration.json"
    path.write_text('{"metadata":{"danger_binning":{"edges":[0,1],"buckets":["a"]}}}')
    monkeypatch.setattr(api, "_calibration_context", CalibrationProvider(path).load)
    with TestClient(api.app) as client:
        response = client.post("/api/ev/rank", json={
            "hand": "123m123p123s11122233z", "turns": 1, "sims": 1,
        })
    assert response.status_code == 200
    assert response.json()["fallback_used"] is True
