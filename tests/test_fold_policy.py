"""MJ-007 executable multi-turn fold policy."""

from taimahjong import ev
from server import api
from taimahjong.danger import OpponentView, parse_river
from taimahjong.tiles import parse_tiles


def test_crafted_late_state_fold_beats_push_from_lower_future_risk():
    hand = parse_tiles("111m999m147p258s13567z")
    opponent = OpponentView(
        parse_river("319m"), [], 0,
        is_dealer=True, dealer_streak=20,
    )
    visible = tuple(1 if tile in (0, 2, 8) else 0 for tile in range(34))

    # The declaration lands on the opponent's first discard, so every later
    # river tile is genbutsu -- 111m999m is six safe copies, enough to defend
    # the whole horizon.  Guard that premise: only discards *after* the
    # declaration count as safe, so a declaration on the last river tile would
    # silently leave zero inventory and make the rest of this test vacuous.
    for safe in (0, 8):
        post = list(hand)
        post[safe] -= 1
        assert ev._is_genbutsu(safe, tuple(post), visible, (opponent,))

    ranked = ev.ev_rank(
        hand, [opponent], visible,
        turns=5, sims=40, seed=17, exhaustive=True,
    )
    fold = next(entry for entry in ranked if entry.is_fold)
    pushes = [entry for entry in ranked if not entry.is_fold]

    # The rest of the hand is six away from tenpai against a streaking dealer,
    # so no push can buy a win -- it can only spend the safe inventory and
    # carry more deal-in risk than a line that keeps folding.
    assert max(entry.p_win for entry in pushes) == 0.0
    assert fold.action_plan is not None
    assert hand[fold.action_plan.first_discard] > 0
    assert fold.action_plan.first_discard in (0, 8)
    assert fold.net_ev > max(entry.net_ev for entry in pushes)
    assert fold.risk_ev < min(entry.risk_ev for entry in pushes)
    assert fold.action_plan.principles


def test_fold_continuation_preserves_repeated_genbutsu():
    current = parse_tiles("112m345p678s1234567z")
    opponent = OpponentView(parse_river("3m12m"), [], 0)
    visible = (1, 1, 1) + (0,) * 31

    # Both 1m and 2m are declared-safe.  Spending 1m leaves another safe copy;
    # spending the singleton 2m would remove that safe kind from inventory.
    assert ev._fold_choice(
        current, visible, (opponent,), None, ev.DEFAULT_SCHEME,
    ) == 0


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
