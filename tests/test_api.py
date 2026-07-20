"""Endpoint coverage for the FastAPI layer (W1 of docs/ui-plan.md)."""

import pytest
from fastapi.testclient import TestClient

from server import api
from taimahjong import endgame


@pytest.fixture(autouse=True)
def fast_budgets(monkeypatch):
    """Shrink the Monte Carlo budgets so endpoint flows stay fast; the verdict
    machinery itself is covered at real budgets by test_quiz/test_trainer."""
    monkeypatch.setattr("taimahjong.quiz.EV_SIMS", 2)
    monkeypatch.setattr("taimahjong.quiz.REFINE_SIMS", 3)
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_SIMS", 4)
    # The lru caches would otherwise leak results computed under other budgets
    # into (or out of) this module's tiny-budget runs.
    from taimahjong import quiz

    for cache in (api._quiz_position, api._endgame_position, quiz._rank_cached):
        cache.cache_clear()
    yield
    for cache in (api._quiz_position, api._endgame_position, quiz._rank_cached):
        cache.cache_clear()


@pytest.fixture()
def client():
    api._SESSIONS.clear()
    return TestClient(api.app)


def _some_hand_tile(position: dict) -> int:
    return next(tile for tile, count in enumerate(position["hand"]) if count)


def test_quiz_new_then_grade_roundtrip(client):
    created = client.post("/api/quiz/new", json={"seed": 1})
    assert created.status_code == 200
    position = created.json()["position"]
    assert sum(position["hand"]) in (17, 14, 11, 8, 5, 2)  # 17 minus 3 per declared meld
    assert position["wall_remaining"] > 0
    assert len(position["opponents"]) == 3

    graded = client.post("/api/quiz/grade", json={"seed": position["seed"], "tile": _some_hand_tile(position)})
    assert graded.status_code == 200
    grade = graded.json()["grade"]
    assert grade["verdict"] in {"best", "good", "inaccuracy", "mistake"}
    assert grade["ranked"] and not any(entry["is_fold"] for entry in grade["ranked"])
    assert isinstance(grade["explain"], str) and grade["explain"]


def test_quiz_grade_rejects_a_tile_not_in_hand(client):
    position = client.post("/api/quiz/new", json={"seed": 1}).json()["position"]
    missing = next(tile for tile, count in enumerate(position["hand"]) if not count)
    response = client.post("/api/quiz/grade", json={"seed": position["seed"], "tile": missing})
    assert response.status_code == 422


def test_endgame_new_meets_the_pressure_filter(client, monkeypatch):
    # Cheap-budget EV gaps are noisy, so pin the gap floor low: the test is the
    # filter plumbing (wall/shanten/declared + tag), not the tuning value.
    monkeypatch.setattr(endgame, "ENDGAME_EV_GAP_MIN", 0.1)
    response = client.post("/api/endgame/new", json={"seed": 1})
    assert response.status_code == 200
    body = response.json()
    position = body["position"]
    assert position["wall_remaining"] <= endgame.ENDGAME_WALL_MAX
    assert position["shanten"] <= endgame.ENDGAME_SHANTEN_MAX or any(
        opponent["declared"] for opponent in position["opponents"]
    )
    assert body["tag"] in {"attack", "defense"}
    assert position["candidate_ev_gap"] >= 0.1

    graded = client.post("/api/endgame/grade", json={"seed": position["seed"], "tile": _some_hand_tile(position)})
    assert graded.status_code == 200
    assert graded.json()["tag"] == body["tag"]


def test_trainer_session_flow_discard_scorecard_and_reload(client):
    started = client.post("/api/trainer/new", json={"seed": 1, "human_seat": 0, "dealer_streak": 1})
    assert started.status_code == 200
    state = started.json()
    session_id = state["session_id"]
    assert state["scorecard"] == {"decisions": 0, "best": 0, "loss": 0.0}

    graded_discards = 0
    for _ in range(40):
        decision = state["decision"]
        if decision["type"] == "outcome":
            assert isinstance(decision["headline"], str)
            break
        if decision["type"] == "discard":
            move = {"step": state["step"], "action": "discard", "tile": _some_hand_tile(decision["position"])}
        else:  # kong or call: exercise the pass path
            move = {"step": state["step"], "action": decision["type"], "option": None}
        acted = client.post(f"/api/trainer/{session_id}/act", json=move)
        assert acted.status_code == 200
        state = acted.json()
        assert state["feedback"]["verdict"] in {"best", "good", "inaccuracy", "mistake"}
        if state["feedback"]["kind"] == "discard":
            graded_discards += 1
        if graded_discards >= 2:
            break
    assert state["scorecard"]["decisions"] >= 1

    # Reload: GET returns the same step, decision, and last feedback.
    reloaded = client.get(f"/api/trainer/{session_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["step"] == state["step"]
    assert reloaded.json()["decision"] == state["decision"]
    assert reloaded.json()["feedback"] == state["feedback"]

    # Replaying a stale step must not advance the game a second time.
    stale = {"step": state["step"] - 1, "action": "discard", "tile": 0}
    assert client.post(f"/api/trainer/{session_id}/act", json=stale).status_code == 409


def test_trainer_act_validates_before_touching_the_generator(client):
    state = client.post("/api/trainer/new", json={"seed": 1}).json()
    session_id = state["session_id"]
    assert state["decision"]["type"] == "discard"
    missing = next(tile for tile, count in enumerate(state["decision"]["position"]["hand"]) if not count)
    bad = client.post(f"/api/trainer/{session_id}/act", json={"step": state["step"], "action": "discard", "tile": missing})
    assert bad.status_code == 422
    # The generator must have survived the rejected move: a legal one still works.
    good_tile = _some_hand_tile(state["decision"]["position"])
    good = client.post(f"/api/trainer/{session_id}/act", json={"step": state["step"], "action": "discard", "tile": good_tile})
    assert good.status_code == 200


def test_trainer_unknown_session_is_404(client):
    assert client.get("/api/trainer/nope").status_code == 404


def test_ev_rank_endpoint_with_opponent(client):
    response = client.post("/api/ev/rank", json={
        "hand": "123m123p123s11122233z",
        "river": "9m9p1z",
        "sims": 4,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["turns"] > 0
    assert any(entry["is_fold"] for entry in body["entries"])
    assert "tenpai_estimate" in body["opponent"]


def test_ev_rank_rejects_melds_without_river(client):
    response = client.post("/api/ev/rank", json={"hand": "123m123p123s11122233z", "melds": "111z"})
    assert response.status_code == 422


def test_score_endpoint_matches_engine(client):
    from taimahjong.scoring import score_hand, WinContext
    from taimahjong.tiles import parse_tiles

    response = client.post("/api/score", json={"hand": "123m111555666777z22z", "win_tile": "2z", "self_draw": True})
    assert response.status_code == 200
    body = response.json()
    expected = score_hand(parse_tiles("123m111555666777z22z"), (), WinContext(winning_tile=_tile("2z"), self_draw=True))
    assert body["total_tai"] == expected.total_tai
    assert body["value_units"] == expected.value_units


def _tile(text: str) -> int:
    from taimahjong.tiles import parse_tiles

    counts = parse_tiles(text)
    return next(tile for tile, count in enumerate(counts) if count)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
