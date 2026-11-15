"""Optional browser regression: PYTHONPATH=. python tests/check_hand_review_browser.py.

Plays one 整場 hand to the end, then checks the post-hand review: one row per
graded decision in play order, each row coloured by the grade the player saw,
the hand's quality score counted from those same row colours (only a pick
inside an unresolved top pair is left out), a row opening that decision's full feedback, the way back landing on
the same row, and the review surviving a reload. No row may be clipped; the
result screen, including the winner's hand and melds, must fit the viewport
without sideways page scrolling at desktop or phone widths.

Uses the existing phone checker and installed Playwright; no new dependency.
"""

import argparse
import math
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, wait_for_server


VIEWPORTS = ((1280, 800), (390, 844), (320, 568))
SEED = 1
LONG = 180000


def _tied(grade):
    """Pick inside an unresolved top pair: shown unranked, no loss charged."""
    pair = grade.get("top1_vs_top2")
    chosen = grade.get("chosen_tile")
    return (grade.get("ranking_state", "clear") != "clear" and pair is not None and chosen is not None
            and chosen in (pair["top_discard"], pair["runner_up_discard"]))


def expected_hand(grades):
    counts = {"best": 0, "good": 0, "inaccuracy": 0, "mistake": 0}
    unresolved = 0
    loss = 0.0
    for grade in grades:
        # Math.round, as stats.js stores it (Python round() is banker's rounding).
        loss += 0.0 if _tied(grade) else math.floor(max(0.0, grade["ev_loss"]) * 100 + 0.5) / 100
        if _tied(grade):
            unresolved += 1
        else:
            counts[grade["verdict"]] += 1
    separable = sum(counts.values())
    score = f"{round(100 * (counts['best'] + counts['good']) / separable)}%" if separable else "—"
    return score, f"{loss:.2f}", unresolved


def row_class(grade):
    return "unresolved" if _tied(grade) else grade["verdict"]


READ_REVIEW = """() => {
  const section = document.querySelector('.hand-review');
  if (!section) return null;
  return {
    score: section.querySelector('.quality-score-card strong').textContent,
    loss: section.querySelector('.quality-minis strong').textContent,
    note: section.querySelector('.quality-note').textContent,
    rows: [...section.querySelectorAll('.hand-review-row')].map(row => ({
      index: Number(row.dataset.review),
      text: row.querySelector('.verdict .text').textContent,
      state: [...row.querySelector('.verdict').classList].find(name => name !== 'verdict'),
    })),
  };
}"""

LAYOUT_PROBLEMS = """() => {
  const problems = [];
  const review = document.querySelector('.hand-review').getBoundingClientRect();
  if (review.right > innerWidth + .5) problems.push('hand review is wider than the viewport');
  document.querySelectorAll('.hand-review-row').forEach(row => {
    const box = row.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) problems.push(`row ${row.dataset.review} has no size`);
    if (box.left < 0 || box.right > innerWidth + .5) problems.push(`row ${row.dataset.review} leaves the viewport`);
    const text = row.querySelector('.verdict .text');
    if (text.scrollWidth > text.clientWidth + 1) problems.push(`row ${row.dataset.review} text is clipped`);
  });
  return problems;
}"""

# The whole result screen must fit, including the winner's declared melds.
VIEWPORT_PROBLEMS = """() => {
  const problems = [];
  if (document.documentElement.scrollWidth > innerWidth)
    problems.push('page scrolls sideways');
  document.querySelectorAll('body *').forEach(node => {
    const box = node.getBoundingClientRect();
    if (box.left < -.5 || box.right > innerWidth + .5)
      problems.push(`${node.getAttribute('class') || node.tagName} leaves the viewport`);
  });
  return [...new Set(problems)];
}"""


def play_hand(page):
    """Discard the first hand tile and pass every call/kong until the outcome."""
    grades = []
    while True:
        page.locator(".outcome, .seat--bottom .handrow button.tile, .callbar .call-btn.pass").first.wait_for(timeout=LONG)
        if page.locator(".outcome").count():
            return grades
        passing = page.locator(".callbar .call-btn.pass")
        target = passing.first if passing.count() else page.locator(".seat--bottom .handrow button.tile").first
        with page.expect_response(lambda response: response.url.endswith("/act"), timeout=LONG) as act:
            target.click()
        grades.append(act.value.json()["feedback"])
        page.get_by_role("button", name="▶").click()


def assert_review(page, grades, label):
    review = page.evaluate(READ_REVIEW)
    assert review is not None, f"{label}: no hand review on the result screen"
    score, loss, unresolved = expected_hand(grades)
    assert (review["score"], review["loss"]) == (score, loss), (label, review, score, loss)
    assert review["note"].startswith(f"{unresolved} 次"), (label, review["note"])
    assert [row["index"] for row in review["rows"]] == list(range(len(grades))), (label, review["rows"])
    for row, grade in zip(review["rows"], grades):
        assert row["text"].startswith(f"第 {row['index'] + 1} 手 · "), row
        assert row["state"] == row_class(grade), (row, grade["verdict"], grade.get("ranking_state"))
        if grade["kind"] == "discard":
            assert row["text"].startswith(f"第 {row['index'] + 1} 手 · 你打 "), row
    return review


def run(browser, url, shots):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("localStorage.setItem('mj-onetap', '1'); localStorage.setItem('mj-scheme', '3-1');")
        page.goto(f"{url}/#/trainer")
        page.locator("#tr-seed").fill(str(SEED))
        page.get_by_role("button", name="開始新局").click()
        grades = play_hand(page)
        assert grades, "the hand must contain at least one graded decision"
        kinds = {grade["kind"] for grade in grades}
        review = assert_review(page, grades, "result")

        # Open the costliest decision: its full feedback, then back to the same row.
        pick = max(range(len(grades)), key=lambda i: (grades[i]["verdict"] != "best", grades[i]["ev_loss"]))
        page.locator(f'.hand-review-row[data-review="{pick}"]').click()
        current = page.locator(".current-decision .verdict")
        current.wait_for(timeout=LONG)
        assert current.locator(".text").text_content() == review["rows"][pick]["text"], "opened the wrong decision"
        assert row_class(grades[pick]) in current.get_attribute("class"), current.get_attribute("class")
        if grades[pick]["kind"] == "discard":
            chosen = grades[pick]["chosen_tile"]
            cut = page.locator(".seat--bottom .handrow > .tile.cut")
            assert cut.count() == 1 and int(cut.get_attribute("data-tile")) == chosen, "replayed hand lost the cut tile"
            assert page.locator(".seat--bottom .tile-score").count() > 0, "replayed hand lost its score badges"
        if shots:
            page.screenshot(path=str(shots / "review-open.png"), full_page=True)
        page.get_by_role("button", name="‹ 回結果").click()
        page.locator(".hand-review").wait_for(timeout=LONG)
        focused = page.evaluate("() => document.activeElement?.dataset?.review ?? null")
        assert focused == str(pick), f"back should return to row {pick}, focus is on {focused}"

        page.reload()
        page.locator(".outcome").wait_for(timeout=LONG)
        assert_review(page, grades, "after reload")

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            if shots:
                page.screenshot(path=str(shots / f"review-{width}.png"), full_page=True)
                page.locator(".outcome").screenshot(path=str(shots / f"outcome-{width}.png"))
            problems = page.evaluate(LAYOUT_PROBLEMS)
            assert not problems, (width, height, problems)
            wide = page.evaluate(VIEWPORT_PROBLEMS)
            assert not wide, (width, height, wide)
        assert not errors, errors
        verdicts = " ".join(row["state"] for row in review["rows"])
        print(f"seed{SEED}: PASS {len(grades)} decisions ({'/'.join(sorted(kinds))}) "
              f"score {review['score']} loss {review['loss']} · {verdicts}", flush=True)
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=Path, default=None, help="directory for screenshots")
    args = parser.parse_args()
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    url = "http://127.0.0.1:8768"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", "8768"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                run(browser, url, args.shots)
            finally:
                browser.close()
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
