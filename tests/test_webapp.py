"""Headless coverage for the Streamlit teaching UI."""

from streamlit.testing.v1 import AppTest

from taimahjong.quiz import generate_position, grade


APP = "webapp/app.py"


def _app() -> AppTest:
    return AppTest.from_file(APP).run(timeout=60)


def test_app_boots_with_four_tabs():
    app = _app()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["單題", "實戰", "切牌分析", "算台"]


def test_trainer_start_then_discard_shows_verdict_and_advances():
    app = _app()
    app.number_input(key="trainer_new_seed").set_value(1)
    app.button(key="trainer_start").click().run(timeout=90)
    # A trainer decision should now be pending: a hand-tile button exists.
    discard = next(b for b in app.button if b.key.startswith("trainer_discard_"))
    discard.click().run(timeout=90)
    assert not app.exception
    # Feedback shown: a verdict message and the "下一手" advance button.
    assert any(b.key == "trainer_next" for b in app.button)
    app.button(key="trainer_next").click().run(timeout=90)
    assert not app.exception


def test_trainer_seat_and_streak_selection_starts_a_non_dealer_hand():
    # The seat/streak selectors must reach play_trainer: starting as 莊的下家
    # (seat 1) with an initial streak puts the human off the dealer seat and
    # records both in session for the cross-hand state machine.
    app = _app()
    app.number_input(key="trainer_new_seed").set_value(1)
    app.selectbox(key="trainer_new_seat").set_value(1)
    app.number_input(key="trainer_new_streak").set_value(2)
    app.button(key="trainer_start").click().run(timeout=90)
    assert not app.exception
    assert app.session_state["trainer_seat"] == 1
    assert app.session_state["trainer_streak"] == 2


def test_trainer_handles_call_decisions_without_error():
    """Drive the trainer a bounded number of steps; if a pon/chi is offered,
    exercise the call UI (choose then advance) and assert nothing crashes."""
    app = _app()
    app.number_input(key="trainer_new_seed").set_value(1)
    app.button(key="trainer_start").click().run(timeout=90)
    exercised_call = False
    for _ in range(10):
        assert not app.exception
        call_buttons = [b for b in app.button if b.key.startswith("trainer_call_")]
        if call_buttons:
            call_buttons[0].click().run(timeout=90)          # choose (option or pass)
            assert not app.exception
            app.button(key="trainer_call_next").click().run(timeout=90)  # advance
            exercised_call = True
            break
        discards = [b for b in app.button if b.key.startswith("trainer_discard_")]
        if not discards:
            break  # game ended
        discards[0].click().run(timeout=90)
        nxt = [b for b in app.button if b.key == "trainer_next"]
        if nxt:
            nxt[0].click().run(timeout=90)
    assert not app.exception
    # The call UI is exercised opportunistically; reaching it is not guaranteed
    # within the step budget, so absence is acceptable, a crash is not.
    _ = exercised_call


def test_quiz_fixed_seed_best_discard_shows_verdict():
    app = _app()
    app.number_input(key="quiz_seed").set_value(1)
    app.button(key="quiz_generate").click().run(timeout=60)
    position = generate_position(1)
    best = grade(position, next(tile for tile, count in enumerate(position.hand) if count)).best.discard
    app.button(key=f"quiz_discard_{best}").click().run(timeout=60)
    assert any("判定：best" in element.value for element in app.success)


def test_quiz_next_question_advances_seed_without_state_error():
    app = _app()
    app.number_input(key="quiz_seed").set_value(1)
    app.button(key="quiz_generate").click().run(timeout=60)
    app.button(key="quiz_next").click().run(timeout=120)
    assert not app.exception
    expected = generate_position(1).seed + 1
    assert app.number_input(key="quiz_seed").value == expected


def test_ev_valid_input_renders_table_and_invalid_hand_is_friendly():
    app = _app()
    app.button(key="ev_run").click().run(timeout=60)
    assert app.dataframe
    app.text_input(key="ev_hand").set_value("not-a-hand")
    app.button(key="ev_run").click().run(timeout=60)
    assert app.error
    assert not app.exception


def test_score_big_three_dragons_total():
    app = _app()
    app.button(key="score_run").click().run(timeout=60)
    assert any("總計：19 台" in element.value for element in app.success)
