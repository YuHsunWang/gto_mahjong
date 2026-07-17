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
