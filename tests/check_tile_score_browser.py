"""Optional browser regression: PYTHONPATH=. python tests/check_tile_score_browser.py.

After a graded discard the hand shows a badge above every evaluated tile: its
net-EV gap to the model's point leader. A player reads the badge instead of the
EV table, so it must say what the grade says: the played tile carries the
verdict's own delta and colour, an unresolved top pair shows no order, and no
badge may be clipped or cover another tile at phone width.

Uses the existing phone checker and installed Playwright; no new dependency.
"""

import argparse
import json
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, wait_for_server


VIEWPORTS = ((1280, 800), (390, 844), (320, 568))
# (seed, which evaluated discard to play). Seeds only pick the position; every
# expectation below is recomputed from the server's own grade payload.
CASES = ((1, "leader"), (1, "last"), (3, "leader"), (3, "last"))
VERDICT_BANDS = {"best": "q-best", "good": "q-correct", "inaccuracy": "q-inaccuracy", "mistake": "q-wrong"}


def _gap_text(gap):
    if gap <= 0:
        return "領先"
    step = Decimal("0.01") if gap < 10 else Decimal("0.1")
    return f"−{Decimal(gap).quantize(step, rounding=ROUND_HALF_UP)}"


def _gap_band(gap):
    if gap <= 0:
        return "q-best"
    if gap <= 0.3:
        return "q-correct"
    return "q-inaccuracy" if gap <= 1 else "q-wrong"


def expected_badges(grade, chosen):
    entries = [entry for entry in grade["ranked"] if not entry["is_fold"]]
    leader = entries[0]["net_ev"]
    pair = grade["top1_vs_top2"]
    unresolved = grade["ranking_state"] != "clear" and pair is not None
    badges = {}
    for entry in entries:
        tile = entry["discard"]
        if unresolved and tile in (pair["top_discard"], pair["runner_up_discard"]):
            badges[tile] = ("≈", "q-unresolved")
        elif tile == chosen:
            badges[tile] = (_gap_text(grade["ev_delta"]), VERDICT_BANDS[grade["verdict"]])
        else:
            gap = leader - entry["net_ev"]
            badges[tile] = (_gap_text(gap), _gap_band(gap))
    return badges


READ_BADGES = """() => {
  const hand = [...document.querySelectorAll('.seat--bottom .handrow > .tile')];
  return hand.filter(tile => tile.querySelector('.tile-score')).map(tile => ({
    tile: Number(tile.dataset.tile),
    text: tile.querySelector('.tile-score').textContent,
    band: [...tile.querySelector('.tile-score').classList].find(name => name.startsWith('q-')),
    mine: Boolean(tile.querySelector('.tile-mine')),
    cut: tile.classList.contains('cut'),
  }));
}"""

LAYOUT_PROBLEMS = """() => {
  const problems = [];
  const hit = (a, b) => a.left < b.right - .5 && b.left < a.right - .5
    && a.top < b.bottom - .5 && b.top < a.bottom - .5;
  const tiles = [...document.querySelectorAll('.seat--bottom .handrow > .tile')];
  const badges = [...document.querySelectorAll('.seat--bottom .tile-score')];
  badges.forEach((badge, index) => {
    const box = badge.getBoundingClientRect();
    const name = `${badge.parentElement.dataset.tile}:${badge.textContent}`;
    if (box.width <= 0 || box.height <= 0) problems.push(`${name} has no size`);
    if (box.left < 0 || box.right > innerWidth || box.top < 0) problems.push(`${name} leaves the viewport`);
    for (let node = badge.parentElement; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
      const clip = node.getBoundingClientRect();
      if (box.left < clip.left - .5 || box.right > clip.right + .5
        || box.top < clip.top - .5 || box.bottom > clip.bottom + .5) {
        problems.push(`${name} is clipped by .${node.className}`);
      }
    }
    badges.slice(index + 1).forEach(other => {
      if (hit(box, other.getBoundingClientRect())) problems.push(`${name} overlaps badge ${other.textContent}`);
    });
    tiles.forEach(tile => {
      if (hit(box, tile.getBoundingClientRect())) problems.push(`${name} covers tile ${tile.dataset.tile}`);
    });
    badge.scrollIntoView({block: 'center'});
    const shown = badge.getBoundingClientRect();
    const top = document.elementFromPoint(shown.left + shown.width / 2, shown.top + shown.height / 2);
    if (top !== badge) problems.push(`${name} is covered by .${top && top.className}`);
  });
  const band = document.querySelector('.seat--bottom').getBoundingClientRect();
  tiles.forEach(tile => {
    const box = tile.getBoundingClientRect();
    if (box.top < band.top - .5 || box.bottom > band.bottom + .5) {
      problems.push(`tile ${tile.dataset.tile} is cut off by the hand band`);
    }
  });
  if (document.documentElement.scrollWidth > innerWidth) problems.push('page scrolls sideways');
  return problems;
}"""


def assert_badges(page, grade, chosen, shots, name):
    expected = expected_badges(grade, chosen)
    shown = page.evaluate(READ_BADGES)
    assert {item["tile"]: (item["text"], item["band"]) for item in shown} == expected, (shown, expected)
    assert len(shown) == len(expected), f"one badge per evaluated tile, got {shown}"
    assert [item["tile"] for item in shown if item["mine"]] == [chosen], shown
    assert all(item["cut"] for item in shown if item["mine"]), shown
    for width, height in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": height})
        if shots:
            page.locator(".table-board").screenshot(path=str(shots / f"{name}-{width}.png"))
        problems = page.evaluate(LAYOUT_PROBLEMS)
        assert not problems, (width, height, problems)
    print(f"{name}: PASS {grade['verdict']}/{grade['ranking_state']} "
          f"{' '.join(text for text, _ in expected.values())}", flush=True)


def _post(page, url, body):
    response = page.request.post(url, data=body, timeout=180000)
    assert response.ok, (url, response.status)
    return response.json()


def run_quiz_case(browser, url, seed, pick, shots):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        body = {"seed": seed, "scheme": "3-1"}
        position = _post(page, f"{url}/api/quiz/new", body)["position"]
        probe_tile = next(tile for tile, count in enumerate(position["hand"]) if count)
        probe = _post(page, f"{url}/api/quiz/grade", {**body, "tile": probe_tile})["grade"]
        ranked = [entry for entry in probe["ranked"] if not entry["is_fold"]]
        chosen = (ranked[0] if pick == "leader" else ranked[-1])["discard"]
        grade = _post(page, f"{url}/api/quiz/grade", {**body, "tile": chosen})["grade"]

        page.add_init_script("localStorage.setItem('mj-onetap', '1'); localStorage.setItem('mj-scheme', '3-1');")
        page.route("**/api/quiz/new", lambda route: route.continue_(post_data=json.dumps(body)))
        page.goto(f"{url}/#/quiz")
        tile = page.locator(f'.seat--bottom .handrow button.tile[data-tile="{chosen}"]').first
        tile.wait_for(timeout=180000)
        assert page.locator(".tile-score").count() == 0, "badges must not show before the discard"
        tile.click()
        page.locator(".seat--bottom .tile-score").first.wait_for(timeout=180000)
        assert_badges(page, grade, chosen, shots, f"quiz-seed{seed}-{pick}")
        assert not errors, errors
        return grade
    finally:
        context.close()


def run_trainer_case(browser, url, shots):
    """整場 feeds the same badges from the act response's feedback."""
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("localStorage.setItem('mj-onetap', '1'); localStorage.setItem('mj-scheme', '3-1');")
        page.goto(f"{url}/#/trainer")
        page.locator("#tr-seed").fill("1")
        page.get_by_role("button", name="開始新局").click()
        tile = page.locator(".seat--bottom .handrow button.tile").first
        tile.wait_for(timeout=180000)
        chosen = int(tile.get_attribute("data-tile"))
        with page.expect_response(lambda response: response.url.endswith("/act"), timeout=180000) as act:
            tile.click()
        feedback = act.value.json()["feedback"]
        assert feedback["kind"] == "discard" and feedback["chosen_tile"] == chosen, feedback
        page.locator(".seat--bottom .tile-score").first.wait_for(timeout=180000)
        assert_badges(page, feedback, chosen, shots, "trainer-seed1")
        assert not errors, errors
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=Path, default=None, help="directory for screenshots")
    args = parser.parse_args()
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    url = "http://127.0.0.1:8767"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", "8767"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                grades = [run_quiz_case(browser, url, seed, pick, args.shots) for seed, pick in CASES]
                run_trainer_case(browser, url, args.shots)
            finally:
                browser.close()
        # The seeds must keep exercising both branches; pick new ones if an
        # engine change makes every case land on the same side.
        states = {grade["ranking_state"] == "clear" for grade in grades}
        assert states == {True, False}, "cases must cover a clear ranking and an unresolved top pair"
        assert any(grade["verdict"] != "best" for grade in grades), "cases must cover a losing discard"
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
