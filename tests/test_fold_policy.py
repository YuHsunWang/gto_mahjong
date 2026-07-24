"""MJ-007 executable multi-turn fold policy."""

from taimahjong import ev
from server import api
from taimahjong.danger import OpponentView, parse_river
from taimahjong.tiles import parse_tiles


def test_crafted_late_state_fold_beats_push_from_lower_future_risk():
    hand = parse_tiles("1112345678999m1234p")
    opponent = OpponentView(
        parse_river("19m"), [], 1,
        is_dealer=True, dealer_streak=20,
    )

    # The crafted late table has six genbutsu inventory copies (1m/9m) against
    # a high-value streaking dealer. Push spends that inventory for shape and
    # incurs more future risk; defense preserves it for the next three turns.
    visible = (1,) + (0,) * 7 + (1,) + (0,) * 25
    ranked = ev.ev_rank(
        hand, [opponent], visible,
        turns=3, sims=40, seed=17, exhaustive=True,
    )
    fold = next(entry for entry in ranked if entry.is_fold)
    pushes = [entry for entry in ranked if not entry.is_fold]

    assert fold.action_plan is not None
    assert hand[fold.action_plan.first_discard] > 0
    assert fold.net_ev > max(entry.net_ev for entry in pushes)
    assert fold.risk_ev < min(entry.risk_ev for entry in pushes)
    assert fold.action_plan.principles


def test_trainer_can_execute_the_returned_fold_first_discard(monkeypatch):
    monkeypatch.setattr("taimahjong.quiz.EV_SIMS", 2)
    monkeypatch.setattr("taimahjong.quiz.REFINE_SIMS", 2)
    monkeypatch.setattr("taimahjong.quiz.ESCALATE_SIMS", 2)
    api._SESSIONS.clear()
    first = api.trainer_new(api.TrainerNewRequest(seed=1))
    original = first["decision"]["position"]["hand"]
    arbitrary = next(tile for tile, count in enumerate(original) if count)
    graded = api.trainer_act(
        first["session_id"],
        api.TrainerActRequest(
            step=first["step"], action="discard", tile=arbitrary,
        ),
    )
    plan = graded["feedback"]["defense_policy"]["action_plan"]

    replay = api.trainer_new(api.TrainerNewRequest(seed=1))
    assert replay["decision"]["position"]["hand"] == original
    assert original[plan["first_discard"]] > 0
    advanced = api.trainer_act(
        replay["session_id"],
        api.TrainerActRequest(
            step=replay["step"],
            action="discard",
            tile=plan["first_discard"],
        ),
    )
    assert advanced["step"] == replay["step"] + 1
