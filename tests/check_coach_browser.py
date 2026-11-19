"""Static coach expressions, unchanged feedback, and left placement in live modes.

Run: PYTHONPATH=. python tests/check_coach_browser.py
Compares feedback textContent to base c254435 using identical API responses.
"""

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, wait_for_server

BASE = "c254435"
VIEWPORTS = ((1280, 900), (667, 375))
EXPRESSIONS = {"best": "happy", "good": "content", "inaccuracy": "puzzled", "mistake": "frown"}
SHOTS = ROOT / ".shots"


def base_source(name):
    return subprocess.check_output(
        ["git", "show", f"{BASE}:server/static/js/{name}.js"], cwd=ROOT, text=True,
    )


def assert_layout(page, selector=".coach-verdict"):
    problems = page.locator(selector).evaluate_all("""nodes => nodes.flatMap(node => {
      const avatar = node.querySelector(':scope > .coach-avatar');
      if (!avatar) return ['missing coach'];
      const box = avatar.getBoundingClientRect();
      const verdict = node.getBoundingClientRect();
      const content = [...node.childNodes].filter(child => child !== avatar);
      const range = document.createRange();
      range.setStartBefore(content[0]); range.setEndAfter(content.at(-1));
      const text = range.getBoundingClientRect();
      const style = getComputedStyle(avatar);
      const issues = [];
      if (box.width <= 0 || box.height <= 0 || !avatar.checkVisibility()) issues.push('hidden coach');
      if (box.right > Math.min(verdict.left, text.left) + .5) issues.push('coach overlaps verdict/text');
      if (box.left < 0 || text.right > innerWidth + .5) issues.push('horizontal overflow');
      if (avatar.textContent !== '') issues.push('coach changes feedback textContent');
      if (avatar.getAttribute('aria-hidden') !== 'true') issues.push('decorative coach is announced');
      if (style.animationName !== 'none' || style.transitionDuration !== '0s') issues.push('animated coach');
      return issues;
    })""")
    assert not problems, problems
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


COMPONENTS = """async () => {
  const current = await import('/js/feedback.js');
  const baseline = await import('/js/baseline-feedback.js');
  const {withCoach} = await import('/js/sparrow-coach.js');
  const root = document.querySelector('main');
  root.replaceChildren();
  const sheet = document.createElement('section');
  sheet.className = 'review-rail';
  sheet.style.cssText = 'position:static;max-width:640px;margin:20px auto';
  root.append(sheet);
  const session = {hands: 1, decisions: 1, counts: {best: 0, good: 1, inaccuracy: 0, mistake: 0},
    qualityScore: 100, unresolved: 0, legacy: 0, avgLossPerHand: 0};
  const cases = ['best', 'good', 'inaccuracy', 'mistake', null].map(verdict => ({verdict, state: 'clear', tile: 1}));
  cases.push(...['uncertain', 'marginal'].flatMap(state => [
    {verdict: 'best', state, tile: 1}, {verdict: 'mistake', state, tile: 3},
  ]));
  const results = [];
  for (const item of cases) {
    const grade = {verdict: item.verdict, marginal: true, ev_delta: .25, ranking_state: item.state,
      top1_vs_top2: {top_discard: 1, runner_up_discard: 2}};
    const text = '你打 二萬';
    const expected = item.state !== 'clear' && item.tile === 1 ? 'content'
      : ({best:'happy', good:'content', inaccuracy:'puzzled', mistake:'frown'}[item.verdict] || 'content');
    const args = [grade, text, item.tile];
    const variants = [
      [current.verdictEl(item.verdict, true, .25, text, {rankingState:item.state, chosenInTopPair:item.tile===1}),
       baseline.verdictEl(item.verdict, true, .25, text, {rankingState:item.state, chosenInTopPair:item.tile===1})],
      [current.gradeVerdictEl(...args), baseline.gradeVerdictEl(...args)],
      ...[item.tile, null].map(chosenTile => {
        const options = {grade, session, chosenTile, choiceText:text};
        return [current.reviewRailEl(options).querySelector('.verdict'), baseline.reviewRailEl(options).querySelector('.verdict')];
      }),
    ];
    for (const [index, [node, old]] of variants.entries()) {
      if (node.textContent !== old.textContent) throw Error('feedback copy changed: ' + JSON.stringify(item));
      const face = node.querySelector('.coach-avatar').dataset.expression;
      const effective = index === 3 ? ({best:'happy', good:'content', inaccuracy:'puzzled', mistake:'frown'}[item.verdict] || 'content') : expected;
      if (face !== effective) throw Error('wrong expression: ' + JSON.stringify({item,index,face,effective}));
      const art = node.querySelector('.coach-avatar');
      const paths = [...art.querySelectorAll('path')].map(path => path.getAttribute('d'));
      const mouth = {happy:'M43 64q7 5 14 0-2 12-8 9Z', content:'M45 66q5 4 10-1',
        puzzled:'m29 40 9-2m23 1 8 3M47 67q4-2 8 0', frown:'m29 40 9 2m23 0 8-2M44 69q6-7 12 0'};
      if (!paths.includes(mouth[effective])) throw Error('expression artwork does not match verdict');
      if (Boolean(art.querySelector('[transform]')) !== (effective === 'puzzled')) throw Error('missing head tilt');
      const lobby = await import('/js/lobby.js');
      const card = lobby.modeCard({hash:'#/quiz', chars:'', desc:''}, 0, null);
      const silhouette = card.querySelector('.lobby-art svg g path:nth-child(2)').getAttribute('d');
      if (paths[1] !== silhouette) throw Error('coach must reuse the original lobby silhouette');
      sheet.append(node);
      results.push(face);
    }
  }
  for (const verdict of [undefined, null, '', 'unresolved', '排名無法分辨']) {
    const node = withCoach(document.createElement('p'), verdict);
    node.append('排名無法分辨');
    if (node.querySelector('svg').dataset.expression !== 'content') throw Error('missing-verdict fallback');
    sheet.append(node);
  }
  return results.length + 5;
}"""


def exercise(page, url, mode):
    page.goto(f"{url}/#/{mode}")
    if mode == "trainer":
        page.locator("#tr-seed").fill("1")
        page.get_by_role("button", name="開始新局").click()
    tiles = page.locator('.seat--bottom .handrow button.tile')
    tiles.first.wait_for(timeout=180000)
    tiles.first.click()
    if mode == "attack-defense":
        page.get_by_text("② 點一張防守牌", exact=False).wait_for()
        tiles.last.click()
        page.get_by_role("heading", name="作答結果").wait_for()
    else:
        page.locator(".current-decision .verdict").wait_for(timeout=180000)


def check_mode(browser, url, mode):
    responses = {}
    errors = []
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_init_script("Math.random = () => 0; localStorage.setItem('mj-onetap', '1');")
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))

    def capture(response):
        if "/api/" in response.url:
            responses[response.url] = response.json()

    page.on("response", capture)
    try:
        exercise(page, url, mode)
        text = page.locator(".review-rail").text_content()
        count = 3 if mode == "attack-defense" else 1
        assert page.locator(".coach-avatar").count() == count
        if mode == "attack-defense":
            grade = responses[f"{url}/api/attack-defense/grade"]["grade"]
            expected = ["happy" if grade[key]["correct"] else "frown" for key in ("attack", "defense")] + ["content"]
        else:
            payload = next(value for key, value in responses.items() if key.endswith("/grade") or key.endswith("/act"))
            grade = payload.get("grade", payload.get("feedback"))
            chosen = grade.get("chosen_tile", grade.get("chosen", {}).get("discard"))
            pair = grade.get("top1_vs_top2") or {}
            unresolved = grade.get("ranking_state", "clear") != "clear" and chosen in (pair.get("top_discard"), pair.get("runner_up_discard"))
            expected = ["content" if unresolved else EXPRESSIONS.get(grade.get("verdict"), "content")]
        actual = page.locator(".coach-avatar").evaluate_all("nodes => nodes.map(node => node.dataset.expression)")
        assert actual == expected, (mode, actual, expected)

        baseline_context = browser.new_context(viewport={"width": 1280, "height": 900})
        try:
            baseline_context.add_init_script("Math.random = () => 0; localStorage.setItem('mj-onetap', '1');")
            for name in ("feedback", "attack-defense"):
                baseline_context.route(f"**/js/{name}.js", lambda route, request, name=name: route.fulfill(content_type="text/javascript", body=base_source(name)))
            baseline_context.route("**/api/**", lambda route: route.fulfill(json=responses[route.request.url]))
            baseline = baseline_context.new_page()
            exercise(baseline, url, mode)
            assert baseline.locator(".review-rail").text_content() == text, f"{mode}: feedback copy changed"
        finally:
            baseline_context.close()
        for theme in "ABCD":
            page.evaluate("theme => document.documentElement.dataset.tableTheme = theme", theme)
            for width, height in VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                assert_layout(page)
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(SHOTS / f"coach-{theme}-{mode}-{width}.png"), full_page=True)
        assert not errors, errors
        print(f"{mode}: PASS ({count} coaches; expression; byte-identical feedback; 8 theme/viewport views)", flush=True)
    finally:
        context.close()


def main():
    SHOTS.mkdir(exist_ok=True)
    url = "http://127.0.0.1:8770"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", "8770"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.route("**/js/baseline-feedback.js", lambda route: route.fulfill(content_type="text/javascript", body=base_source("feedback")))
                page.goto(url)
                cases = page.evaluate(COMPONENTS)
                for theme in "ABCD":
                    page.evaluate("theme => document.documentElement.dataset.tableTheme = theme", theme)
                    for width, height in VIEWPORTS:
                        page.set_viewport_size({"width": width, "height": height})
                        assert_layout(page)
                        page.screenshot(path=str(SHOTS / f"coach-{theme}-expressions-{width}.png"), full_page=True)
                print(f"Components: PASS ({cases} mapping/copy cases; 8 theme/viewport views)", flush=True)
                page.close()
                for mode in ("quiz", "trainer", "attack-defense", "endgame"):
                    check_mode(browser, url, mode)
            finally:
                browser.close()
        print("Coach: PASS (41 component cases; 4 live modes; 40 screenshots)", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
