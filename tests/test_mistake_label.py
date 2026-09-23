"""Offline coverage for the optional Jev mistake label (DEV-201).

The label is advisory: it must never appear when it would contradict the
engine's own verdict, and it must never cost the player their feedback.  The
SDK is replaced by a stub so these tests stay offline and key-free.
"""

import logging
import sys
import types

import pytest

import taimahjong.mistake_label as mistake_label
from taimahjong.ev import EVRankEntry
from taimahjong.quiz import QuizGrade, generate_position


@pytest.fixture(scope="module")
def position():
    return generate_position(1)


def _entry(discard, attack_ev):
    return EVRankEntry(discard, 0.0, None, attack_ev, (), 0.0, attack_ev)


def _grade(position, *, chosen_rank=1, ev_delta=0.5):
    """A graded mistake over three legal discards from the real position."""
    tiles = [tile for tile, count in enumerate(position.hand) if count][:3]
    ranked = tuple(_entry(tile, 3.0 - index) for index, tile in enumerate(tiles))
    return QuizGrade(
        position, ranked[0], ranked[chosen_rank], ranked, ev_delta, chosen_rank + 1, "mistake",
    )


class _Answer:
    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence, "no_concept_error": 1.0 - confidence}


@pytest.fixture
def sdk(monkeypatch):
    """Install a stub ``typesafe_sdk`` and record every question it is asked."""
    calls = []
    reply = {"answer": _Answer("broke_wide_shape", 0.8), "raise": None}

    class TypeSafeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def system_one(self, state, questions):
            calls.append((state, questions))
            if reply["raise"] is not None:
                raise reply["raise"]
            return types.SimpleNamespace(answers={"mistake": reply["answer"]})

    module = types.ModuleType("typesafe_sdk")
    module.TypeSafeClient = TypeSafeClient
    module.Choice = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "typesafe_sdk", module)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    return types.SimpleNamespace(calls=calls, reply=reply)


def test_build_state_reports_the_engine_numbers_it_was_given(position):
    result = _grade(position)
    state = mistake_label.build_state(result)
    assert state["ev_delta"] == 0.5
    assert state["best"]["net_ev"] == 3.0
    assert state["chosen"]["net_ev"] == 2.0
    assert state["best"]["tile"] != state["chosen"]["tile"]
    assert set(state["engine_components"]) == {"best", "chosen"}


def test_confident_label_on_a_clear_mistake_is_returned(position, sdk):
    label = mistake_label.label_mistake(_grade(position))
    assert label is not None and label.label == "broke_wide_shape"
    assert len(sdk.calls) == 1


def test_no_key_means_no_question_and_no_label(position, sdk, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert mistake_label.label_mistake(_grade(position)) is None
    assert sdk.calls == []


def test_a_discard_the_engine_did_not_rank_lower_is_never_labelled(position, sdk):
    assert mistake_label.label_mistake(_grade(position, ev_delta=0.0)) is None
    assert mistake_label.label_mistake(_grade(position, chosen_rank=0)) is None
    assert sdk.calls == []


def test_unresolved_top_pair_is_not_labelled_but_a_lower_choice_is(position, sdk, monkeypatch):
    # Labelling one of two discards the screen calls indistinguishable would
    # contradict the verdict shown beside it.
    monkeypatch.setattr(QuizGrade, "ranking_state", property(lambda self: "uncertain"))
    assert mistake_label.label_mistake(_grade(position, chosen_rank=1)) is None
    assert sdk.calls == []
    assert mistake_label.label_mistake(_grade(position, chosen_rank=2)) is not None


@pytest.mark.parametrize(
    ("choice", "confidence", "shown"),
    [
        ("broke_wide_shape", mistake_label.MIN_CONFIDENCE, True),
        ("broke_wide_shape", mistake_label.MIN_CONFIDENCE - 0.01, False),
        ("no_concept_error", 0.99, False),
    ],
)
def test_confidence_gate_and_no_match_withhold_the_label(position, sdk, choice, confidence, shown):
    sdk.reply["answer"] = _Answer(choice, confidence)
    assert (mistake_label.label_mistake(_grade(position)) is not None) is shown


def test_sdk_failure_falls_back_and_is_logged(position, sdk, caplog):
    sdk.reply["raise"] = RuntimeError("network down")
    with caplog.at_level(logging.WARNING, logger=mistake_label.__name__):
        assert mistake_label.label_mistake(_grade(position)) is None
    assert "mistake label unavailable" in caplog.text
