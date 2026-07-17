"""Headless coverage for the Streamlit teaching UI."""

from streamlit.testing.v1 import AppTest

from taimahjong.quiz import generate_position, grade


APP = "webapp/app.py"


def _app() -> AppTest:
    return AppTest.from_file(APP).run(timeout=60)


def test_app_boots_with_three_tabs():
    app = _app()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["練習", "切牌分析", "算台"]


def test_quiz_fixed_seed_best_discard_shows_verdict():
    app = _app()
    app.number_input(key="quiz_seed").set_value(1)
    app.button(key="quiz_generate").click().run(timeout=60)
    position = generate_position(1)
    best = grade(position, next(tile for tile, count in enumerate(position.hand) if count)).best.discard
    app.button(key=f"quiz_discard_{best}").click().run(timeout=60)
    assert any("判定：best" in element.value for element in app.success)


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
