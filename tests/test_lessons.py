"""Offline lesson matching and engine corroboration for issue #57."""

import logging
import sys
import types

import pytest
from fastapi.testclient import TestClient

from taimahjong import lessons, mistake_label
from taimahjong.danger import OpponentView, danger_score, fold_score, parse_river, tenpai_score
from taimahjong.ev import EVRankEntry, remaining_draws
from taimahjong.quiz import QuizGrade, QuizOpponent, QuizPosition, grade
from taimahjong.shanten import shanten
from taimahjong.tiles import parse_tiles
from taimahjong.ukeire import discard_analysis


pytestmark = pytest.mark.timeout(30)


def _tile(text):
    return next(i for i, count in enumerate(parse_tiles(text)) if count)


def _position(lesson):
    hand = tuple(parse_tiles(lesson["hand"]))
    own_river = tuple(parse_river(lesson["own_river"]))
    melds = tuple(
        tuple(tile for tile, count in enumerate(parse_tiles(meld)) for _ in range(count))
        for meld in lesson.get("own_melds", [])
    )
    rivers = [tuple(parse_river(op["river"])) for op in lesson["opponents"]]
    public = [0] * 34
    for river in [own_river, *rivers]:
        for entry in river:
            public[entry.tile] += 1
    for meld in melds:
        for tile in meld:
            public[tile] += 1
    opponents = []
    for op, river in zip(lesson["opponents"], rivers):
        view = OpponentView(list(river), [], op["declared_at"], hand_count=16)
        others = public.copy()
        for entry in river:
            others[entry.tile] -= 1
        opponents.append(QuizOpponent(
            op["seat"], river, (), op["declared_at"], tenpai_score(view).score,
            fold_score(view, others), hand_count=16,
        ))
    visible = tuple(h + p for h, p in zip(hand, public))
    assert max(visible) <= 4
    # Four concealed hands, the public rivers, live wall and 14-tile reserve.
    assert sum(hand) + 3 * 16 + sum(public) + lesson["wall_remaining"] + 14 == 136
    return QuizPosition(
        seed=lesson["seed"], seat=lesson["seat"], turn=lesson["turn"],
        drawn_tile=_tile(lesson["drawn_tile"]), hand=hand, own_river=own_river,
        own_melds=melds, opponents=tuple(opponents), public_counts=tuple(public),
        visible_counts=visible, shanten=shanten(hand, len(melds)),
        draws_remaining=remaining_draws(hand, public, wall_remaining=lesson["wall_remaining"]),
        wall_remaining=lesson["wall_remaining"], candidate_ev_gap=0.0,
        opening_live_draw=False,
    )


@pytest.fixture
def mistake():
    position = _position(next(l for l in lessons.LESSONS if l["id"] == "keep-attacking"))
    tiles = [_tile("5p"), _tile("3m"), _tile("7s")]
    ranked = tuple(EVRankEntry(tile, 0.0, None, 3.0 - i, (), 0.0, 3.0 - i)
                   for i, tile in enumerate(tiles))
    return QuizGrade(position, ranked[0], ranked[1], ranked, 1.0, 2, "mistake")


@pytest.fixture
def sdk(monkeypatch):
    calls = []
    reply = types.SimpleNamespace(
        scores={l["id"]: 0.0 for l in lessons.LESSONS}, error=None,
        choice="broke_wide_shape", confidence=0.9, label_error=None,
    )

    class TypeSafeClient:
        def __init__(self, timeout):
            assert timeout == mistake_label.TIMEOUT_SECONDS

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def system_one(self, state, questions):
            calls.append((state, questions))
            if "mistake" in questions:
                if reply.label_error:
                    raise reply.label_error
                return types.SimpleNamespace(answers={"mistake": types.SimpleNamespace(
                    choice=reply.choice, confidence=reply.confidence,
                    probabilities={reply.choice: reply.confidence},
                )})
            if reply.error:
                raise reply.error
            return types.SimpleNamespace(answers={
                key: types.SimpleNamespace(score=score) for key, score in reply.scores.items()
            })

    module = types.ModuleType("typesafe_sdk")
    module.TypeSafeClient = TypeSafeClient
    module.Score = lambda **kwargs: kwargs
    module.Choice = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "typesafe_sdk", module)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    return types.SimpleNamespace(calls=calls, reply=reply)


@pytest.mark.parametrize(("label", "lesson_id"), [
    ("rushed_narrow_wait", "rush-vs-wide"),
    ("broke_wide_shape", "lone-terminal"),
    ("ignored_danger", "respect-threat"),
    ("over_defensive", "keep-attacking"),
    ("wrong_pair_choice", "pair-vs-run"),
    ("no_concept_error", None),
])
def test_every_label_has_its_approved_mapping_without_a_fallback(mistake, sdk, label, lesson_id):
    assert set(lessons.LABEL_LESSONS) == set(mistake_label.LABELS)
    matched = lessons.match_lesson(mistake, mistake_label.MistakeLabel(label, 0.9, {}))
    assert (None if matched is None else matched.lesson_id) == lesson_id
    if matched:
        assert matched.source == "label"
        assert matched.lesson_id in {l["id"] for l in lessons.LESSONS}
    assert sdk.calls == []


@pytest.mark.parametrize("score", [lessons.MIN_RELEVANCE, 2.9, lessons.MIN_RELEVANCE - 0.01])
def test_fallback_scores_every_lesson_and_picks_only_the_top_above_threshold(mistake, sdk, score):
    sdk.reply.scores.update({"pair-vs-run": score, "lone-terminal": score - 0.1})
    matched = lessons.match_lesson(mistake, None)
    if score < lessons.MIN_RELEVANCE:
        assert matched is None
    else:
        assert matched.lesson_id == "pair-vs-run"
        assert matched.source == "jev"
        assert matched.scores == sdk.reply.scores
    state, questions = sdk.calls[0]
    assert state == mistake_label.build_state(mistake)
    assert set(questions) == {l["id"] for l in lessons.LESSONS}
    assert all(q["criteria"] == lessons.RELEVANCE_CRITERIA for q in questions.values())


def test_fallback_tie_uses_catalog_order(mistake, sdk):
    sdk.reply.scores.update({"lone-terminal": 3, "pair-vs-run": 3})
    assert lessons.match_lesson(mistake, None).lesson_id == "lone-terminal"


def test_non_mistakes_and_unresolved_top_pair_never_call_jev(mistake, sdk, monkeypatch):
    from dataclasses import replace

    for result in (replace(mistake, ev_delta=0), replace(mistake, chosen=mistake.best)):
        assert lessons.match_lesson(result, None) is None
    monkeypatch.setattr(QuizGrade, "ranking_state", property(lambda self: "uncertain"))
    assert lessons.match_lesson(mistake, None) is None
    assert sdk.calls == []


@pytest.mark.parametrize("failure", ["key", "sdk", "request", "malformed"])
def test_unavailable_fallback_keeps_grading_usable(mistake, sdk, monkeypatch, caplog, failure):
    if failure == "key":
        monkeypatch.delenv("TYPESAFE_API_KEY")
    elif failure == "sdk":
        monkeypatch.setitem(sys.modules, "typesafe_sdk", None)
    elif failure == "request":
        sdk.reply.error = RuntimeError("network unavailable")
    else:
        sdk.reply.scores["lone-terminal"] = float("nan")
    with caplog.at_level(logging.WARNING, logger=lessons.__name__):
        assert lessons.match_lesson(mistake, None) is None
    if failure in ("request", "malformed"):
        assert "lesson matching unavailable" in caplog.text


@pytest.mark.parametrize("mode", ["label", "low-confidence", "failed", "no-concept"])
def test_grade_payload_preserves_label_status_and_lesson_source(mistake, sdk, mode):
    from server.api import _grade_payload

    sdk.reply.scores["keep-attacking"] = 2.9
    if mode == "low-confidence":
        sdk.reply.confidence = mistake_label.MIN_CONFIDENCE - 0.01
    elif mode == "failed":
        sdk.reply.label_error = RuntimeError("label request failed")
    elif mode == "no-concept":
        sdk.reply.choice = "no_concept_error"
    payload = _grade_payload(mistake)
    if mode == "no-concept":
        assert payload["matched_lesson"] is None
        assert payload["mistake_label"] is None
        assert len(sdk.calls) == 1
    else:
        assert payload["matched_lesson"]["source"] == ("label" if mode == "label" else "jev")
        assert payload["matched_lesson"]["id"] == ("lone-terminal" if mode == "label" else "keep-attacking")
        assert len(sdk.calls) == (1 if mode == "label" else 2)
        assert bool(payload["mistake_label"]) is (mode == "label")
    assert payload["best"]["net_ev"] == mistake.best.net_ev
    assert payload["ev_delta"] == mistake.ev_delta


@pytest.mark.parametrize("lesson", [l for l in lessons.LESSONS if l["kind"] == "danger"], ids=lambda l: l["id"])
def test_danger_lesson_answer_agrees_with_production_trainer_ranking(lesson):
    result = grade(_position(lesson), _tile(lesson["recommend"]))
    assert result.best.discard == _tile(lesson["recommend"])
    assert result.ranked[0].discard == result.best.discard
    assert result.ranked[0].net_ev - result.ranked[1].net_ev > 0.3
    assert result.ranking_state == "clear"
    assert result.ev_delta == 0
    alternative = "5p" if lesson["id"] == "respect-threat" else "3m"
    comparison = grade(result.position, _tile(alternative))
    assert comparison.best.discard == result.best.discard
    assert comparison.ranking_state == "clear"
    assert comparison.ev_delta > 0.3
    if lesson["id"] == "respect-threat":
        # The safe answer must pay attack value for reduced loss, rather than
        # merely avoid an exhausted wait as the old position did.
        other = next(e for e in comparison.ranked if e.discard == _tile(alternative))
        assert result.best.risk_ev < other.risk_ev
        assert result.best.attack_ev < other.attack_ev


def test_danger_positions_have_distinct_hands_and_real_attack_defense_tradeoffs():
    hands = [tuple(parse_tiles(lesson["hand"])) for lesson in lessons.LESSONS]
    assert len(hands) == len(set(hands))
    for lesson in lessons.LESSONS:
        if lesson["kind"] != "danger":
            continue
        position = _position(lesson)
        assert not position.own_melds
        rows = discard_analysis(position.hand, 0, position.public_counts)
        assert rows[0].discard == _tile("5p")
        by_tile = {row.discard: row for row in rows}
        if lesson["id"] == "respect-threat":
            assert (rows[0].shanten_after, rows[0].total) == (0, 3)
            assert rows[0].ukeire == {_tile("2s"): 0, _tile("5s"): 1, _tile("8s"): 2}
            safe = by_tile[_tile("2s")]
            assert (safe.shanten_after, safe.ukeire) == (0, {_tile("5p"): 2})
            for opponent in position.opponents:
                assert opponent.declared
                post = list(position.hand)
                post[_tile("2s")] -= 1
                assert "declared_safe" in danger_score(
                    _tile("2s"), opponent.view(), position.public_counts, post,
                ).modifiers
                post = list(position.hand)
                post[_tile("5p")] -= 1
                assert danger_score(_tile("5p"), opponent.view(), position.public_counts, post).score > 0
        else:
            assert (rows[0].shanten_after, rows[0].total) == (0, 9)
            assert rows[0].ukeire == {_tile("1s"): 3, _tile("4s"): 3, _tile("7s"): 3}
            assert by_tile[_tile("3m")].shanten_after == 1
            for opponent in position.opponents:
                assert not opponent.declared and not opponent.melds
                assert _tile("3m") in {entry.tile for entry in opponent.river}


def test_catalog_and_all_efficiency_answers_are_corroborated_by_api():
    from server.api import app

    with TestClient(app) as client:
        assert client.get("/api/lessons").json() == lessons.LESSONS
        expected = {"lone-terminal": (0, 11), "widest-wait": (0, 6),
                    "rush-vs-wide": (1, 29), "pair-vs-run": (0, 4)}
        for lesson in lessons.LESSONS:
            if lesson["kind"] == "discard":
                response = client.post("/api/ukeire", json={"hand": lesson["hand"]})
                assert response.status_code == 200
                row = next(r for r in response.json()["discards"] if r["discard"] == _tile(lesson["recommend"]))
                assert (row["shanten_after"], row["total"]) == expected[lesson["id"]]
            elif lesson["kind"] == "compare":
                for option, expected_row in zip(lesson["options"], [(1, 23), (0, 11)]):
                    response = client.post("/api/ukeire", json={k: v for k, v in option.items() if k != "label"})
                    assert response.status_code == 200
                    body = response.json()
                    assert (body["shanten"], body["total"]) == expected_row
