"""Run with PYTHONPATH=. python tests/check_hand_review_browser.py.

Play an 整場 hand against the server on port 8766. Compare the 牌譜 table at
each frame with the original API decision and verify the replay controls,
verdicts, explanation, reload, and desktop and landscape phone layouts.
"""

import argparse
import math
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import wait_for_server


VIEWPORTS = ((1440, 900), (844, 390), (740, 360), (667, 375))
SEED = 1
LONG = 180000


def _tied(grade):
    """Pick inside an unresolved top pair: shown unranked, no loss charged.

    Mirrors choiceIsUnresolved in stats.js: a call or kong is tied when its
    choice (None = pass) is among indistinguishable_indices."""
    if grade.get("ranking_state", "clear") == "clear":
        return False
    if grade["kind"] in ("call", "kong"):
        return grade["choice"] in grade.get("indistinguishable_indices", [])
    pair = grade.get("top1_vs_top2")
    chosen = grade.get("chosen_tile")
    return pair is not None and chosen is not None and chosen in (pair["top_discard"], pair["runner_up_discard"])


# A call the model cannot rank against its runner-up must show ≈, never the
# 模型領先 seal (#125). Seed 1 may not produce one, so feed the modules one.
CALL_TIE = """async () => {
  const { gradeVerdictEl } = await import('/js/feedback.js');
  const { choiceIsUnresolved } = await import('/js/stats.js');
  const base = { kind: 'call', verdict: 'best', marginal: false, ev_delta: 0, ev_loss: 0 };
  const tied = { ...base, choice: null, ranking_state: 'uncertain', indistinguishable_indices: [0, null] };
  const clear = { ...base, choice: 1, ranking_state: 'uncertain', indistinguishable_indices: [0, null] };
  const read = (grade) => {
    const el = gradeVerdictEl(grade, '');
    return { cls: el.className, badge: el.querySelector('.badge').textContent, rule: choiceIsUnresolved(grade) };
  };
  return { tied: read(tied), clear: read(clear) };
}"""


VERDICT_LABELS = {"best": "模型領先", "good": "正確", "inaccuracy": "小失誤", "mistake": "失誤"}


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
    leading = counts["best"] + counts["good"]
    score = f"{math.floor(100 * leading / separable + 0.5)}%" if separable else "—"
    stats = {
        "decisions": str(len(grades)),
        "separable": str(separable),
        "leading": str(leading),
        "score": score,
        "loss": f"{loss:.2f}",
    }
    return stats, {**counts, "unresolved": unresolved}


def verdict_class(grade):
    return "unresolved" if _tied(grade) else grade["verdict"]


def expected_pill(grade):
    return "≈" if _tied(grade) else VERDICT_LABELS[grade["verdict"]]


READ_REVIEW = """() => {
  const section = document.querySelector('.hand-review');
  if (!section) return null;
  const tally = [...section.querySelectorAll('.hand-tally li')];
  return {
    title: section.querySelector('h2').textContent,
    stats: Object.fromEntries([...section.querySelectorAll('.hand-review-summary [data-stat]')].map(node => [node.dataset.stat, node.textContent])),
    tally: Object.fromEntries(tally.map(item =>
      [item.dataset.verdict, Number(item.querySelector('.tally-count').textContent)])),
    colors: Object.fromEntries(tally.map(item =>
      [item.dataset.verdict, getComputedStyle(item.querySelector('.tally-count')).backgroundColor])),
    retired: document.querySelectorAll('.quality-score-card, .quality-bar, .quality-row, .hand-review-row, .hand-river').length,
    cells: [...section.querySelectorAll('.replay-timeline button')].map(cell => ({
      label: cell.getAttribute('aria-label'),
      state: cell.classList[1],
      color: getComputedStyle(cell).backgroundColor,
    })),
  };
}"""

READ_FRAME = """() => {
  const replay = document.querySelector('.hand-replay');
  const all = selector => [...replay.querySelectorAll(selector)];
  const one = selector => replay.querySelector(selector);
  const pill = one('.replay-pill');
  return {
    current: all('.replay-timeline button').flatMap((cell, index) => cell.hasAttribute('aria-current') ? [index] : []),
    progress: one('.replay-progress').textContent,
    pill: pill.textContent,
    verdict: pill.classList[1],
    color: getComputedStyle(pill).backgroundColor,
    choice: one('.replay-choice').textContent,
    recommendation: one('.replay-recommendation').textContent,
    hand: all('.seat--bottom .handrow > .tile').map(tile => Number(tile.dataset.tile)).sort((a, b) => a - b),
    chosen: all('.felt .tile.cut').map(tile => tile.title),
    offered: one('.offered .tile')?.title ?? null,
    wall: Number(all('.center-stats strong')[1].textContent),
    seats: Object.fromEntries(['bottom', 'right', 'top', 'left'].map(side => {
      const seat = one('.seat--' + side);
      const river = all('.river--' + side + ' > .tile');
      const melds = [...seat.querySelectorAll('.hand-meld, .seat-meld')];
      return [seat.dataset.seat, {
        river: river.map(tile => tile.title),
        fresh: river.flatMap((tile, index) => tile.classList.contains('replay-new') ? [index] : []),
        visibleHighlight: river.every(tile => {
          const style = getComputedStyle(tile);
          return !tile.classList.contains('replay-new') || (style.outlineStyle === 'solid' && parseFloat(style.outlineWidth) >= 2);
        }),
        melds: melds.map(meld => [...meld.querySelectorAll('.tile')].map(tile => tile.title || '覆蓋的牌').sort()),
      }];
    })),
  };
}"""

# The whole result screen must fit, including the winner's declared melds.
VIEWPORT_PROBLEMS = """() => {
  const problems = [];
  if (document.documentElement.scrollWidth > innerWidth)
    problems.push('page scrolls sideways');
  const table = document.querySelector('.hand-replay .table-scroll');
  if (table.scrollWidth > table.clientWidth + 1)
    problems.push('replay table scrolls sideways');
  document.querySelectorAll('body *').forEach(node => {
    const box = node.getBoundingClientRect();
    if (box.left < -.5 || box.right > innerWidth + .5)
      problems.push(`${node.getAttribute('class') || node.tagName} leaves the viewport`);
  });
  return [...new Set(problems)];
}"""


def play_hand(page, decision):
    """Discard the first hand tile and pass every call/kong until the outcome."""
    frames = []
    while True:
        page.locator(".outcome, .seat--bottom .handrow button.tile, .callbar .call-btn.pass").first.wait_for(timeout=LONG)
        if page.locator(".outcome").count():
            return frames
        passing = page.locator(".callbar .call-btn.pass")
        target = passing.first if passing.count() else page.locator(".seat--bottom .handrow button.tile").first
        with page.expect_response(lambda response: response.url.endswith("/act"), timeout=LONG) as act:
            target.click()
        response = act.value.json()
        frames.append((decision, response["feedback"]))
        decision = response["decision"]
        page.get_by_role("button", name="▶").click()


def assert_review(page, grades, label):
    review = page.evaluate(READ_REVIEW)
    assert review is not None, f"{label}: no hand review on the result screen"
    assert review["title"] == "這一局的牌譜", (label, review["title"])
    assert review["retired"] == 0, f"{label}: retired hand review UI is still drawn"
    stats, tally = expected_hand(grades)
    assert review["stats"] == stats, (label, review["stats"], stats)
    assert review["tally"] == tally, (label, review["tally"], tally)
    assert len(review["cells"]) == len(grades), (label, review["cells"])
    for number, (cell, grade) in enumerate(zip(review["cells"], grades), 1):
        verdict = verdict_class(grade)
        text = "≈ 無法區分" if _tied(grade) else expected_pill(grade)
        assert cell == {"state": verdict, "label": f"第 {number} 手，{text}", "color": review["colors"][verdict]}, cell
    return review


def face(tile):
    if tile < 27:
        return "一二三四五六七八九"[tile % 9] + "萬筒條"[tile // 9]
    return "東南西北白發中"[tile - 27]


def option_text(decision, index):
    if index is None:
        return "過（不鳴）" if decision["type"] == "call" else "不槓"
    option = decision["options"][index]
    if decision["type"] == "call":
        return ("碰" if option["kind"] == "pon" else "吃") + " " + "".join(map(face, option["meld"]))
    return ("暗槓" if option["kind"] == "concealed" else "加槓") + " " + face(option["tile"])


def meld_faces(melds, kongs, own=False):
    """The trainer API includes legacy triplets for opponents' open kongs."""
    if not own:
        melds = melds[:len(melds) - sum(not kong["concealed"] for kong in kongs)]
    groups = [sorted(map(face, meld)) for meld in melds]
    for kong in kongs:
        hidden = (2 if own else 4) if kong["concealed"] else 0
        tiles = [face(kong["tile"])] * (4 - hidden) if hidden < 4 else []
        groups.append(sorted(tiles + ["覆蓋的牌"] * hidden))
    return groups


def assert_frame(page, frames, index, colors):
    decision, grade = frames[index]
    position = decision["position"]
    shown = page.evaluate(READ_FRAME)
    verdict = verdict_class(grade)
    assert shown["current"] == [index], (index, shown["current"])
    assert shown["progress"] == f"第 {index + 1} / {len(frames)} 手", shown["progress"]
    assert (shown["pill"], shown["verdict"], shown["color"]) == (expected_pill(grade), verdict, colors[verdict]), shown
    assert shown["wall"] == position["wall_remaining"], (index, shown["wall"], position["wall_remaining"])
    assert shown["hand"] == [tile for tile, count in enumerate(position["hand"]) for _ in range(count)], (index, shown["hand"])
    chosen = []
    offered = None
    unresolved = grade.get("ranking_state", "clear") != "clear"
    if grade["kind"] == "discard":
        chosen = [face(grade["chosen_tile"])]
        choice = f"你打 {chosen[0]}"
        pair = grade.get("top1_vs_top2")
        best = [pair["top_discard"], pair["runner_up_discard"]] if unresolved and pair else [grade["best"]["discard"]]
        recommendation = " ≈ ".join(map(face, best))
    else:
        choice = f"你選擇：{option_text(decision, grade['choice'])}"
        tied = grade.get("indistinguishable_indices", [])
        best = tied if unresolved and len(tied) > 1 else [grade["best_index"]]
        recommendation = " ≈ ".join(option_text(decision, option) for option in best)
        if grade["kind"] == "call":
            offered = face(decision["offered_tile"])
            if grade["choice"] is not None:
                chosen = [offered]
        elif grade["choice"] is not None:
            chosen = [face(decision["options"][grade["choice"]]["tile"])]
    assert shown["choice"] == choice, (index, shown["choice"], choice)
    assert shown["recommendation"] == f"模型建議：{recommendation}", (index, shown["recommendation"], recommendation)
    assert shown["chosen"] == chosen and shown["offered"] == offered, (index, shown["chosen"], shown["offered"])

    previous = frames[index - 1][0]["position"]["opponents"] if index else []
    lengths = {opponent["seat"]: len(opponent["river"]) for opponent in previous}
    expected = [(position["seat"], position["own_river"], [],
                 meld_faces(position["own_melds"], position["own_kong_details"], own=True))]
    for opponent in position["opponents"]:
        seat, river = opponent["seat"], opponent["river"]
        start = lengths.get(seat, len(river))
        expected.append((seat, river, list(range(start, len(river))),
                         meld_faces(opponent["melds"], opponent["kong_details"])))
    for seat, river, fresh, melds in expected:
        actual = shown["seats"][str(seat)]
        assert actual["river"] == [face(entry["tile"]) for entry in river], (index, seat, "river", actual["river"], river)
        assert actual["fresh"] == fresh, (index, seat, "new river tiles", actual["fresh"], fresh)
        assert actual["visibleHighlight"], (index, seat, "missing highlight outline")
        assert actual["melds"] == melds, (index, seat, "melds", actual["melds"], melds)
    return shown


def run(browser, url, shots):
    width, height = VIEWPORTS[0]
    context = browser.new_context(viewport={"width": width, "height": height})
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("localStorage.setItem('mj-onetap', '1'); localStorage.setItem('mj-scheme', '3-1');")
        page.goto(f"{url}/#/trainer")
        call = page.evaluate(CALL_TIE)
        assert call["tied"]["rule"] and "unresolved" in call["tied"]["cls"].split() \
            and call["tied"]["badge"].startswith("≈") and "模型領先" not in call["tied"]["badge"], call
        assert not call["clear"]["rule"] and "unresolved" not in call["clear"]["cls"].split(), call
        page.locator("#tr-seed").fill(str(SEED))
        with page.expect_response(lambda response: response.url.endswith("/api/trainer/new"), timeout=LONG) as start:
            page.get_by_role("button", name="開始新局").click()
        frames = play_hand(page, start.value.json()["decision"])
        assert len(frames) > 2, "the hand must have enough decisions to exercise stepping and playback"
        grades = [grade for _, grade in frames]
        kinds = {grade["kind"] for grade in grades}
        review = assert_review(page, grades, "result")
        colors = review["colors"]

        replay = page.locator(".hand-replay")
        cells = replay.locator(".replay-timeline button")
        prev = replay.get_by_role("button", name="上一手")
        next_move = replay.get_by_role("button", name="下一手")
        play = replay.get_by_role("button", name="播放", exact=True)
        pause = replay.get_by_role("button", name="暫停", exact=True)
        explain = replay.get_by_role("button", name="看解說")
        first = assert_frame(page, frames, 0, colors)
        assert prev.is_disabled(), "previous must be disabled on the first frame"
        page.locator(".outcome .btn").first.focus()
        page.keyboard.press("ArrowRight")
        assert_frame(page, frames, 0, colors)
        next_move.click()
        second = assert_frame(page, frames, 1, colors)
        assert first["seats"] != second["seats"], "fixture must have different rivers or melds in the first two frames"
        prev.click()
        assert_frame(page, frames, 0, colors)
        replay.locator(".table-scroll").focus()
        page.keyboard.press("ArrowRight")
        assert_frame(page, frames, 1, colors)
        page.keyboard.press("ArrowLeft")
        assert_frame(page, frames, 0, colors)

        highlighted = False
        for index in range(1, len(frames)):
            cells.nth(index).click()
            shown = assert_frame(page, frames, index, colors)
            highlighted |= any(seat["fresh"] for seat in shown["seats"].values())
        assert highlighted, "fixture must add opponent river tiles"
        assert next_move.is_disabled(), "next must be disabled at the last frame"

        page.clock.install()
        cells.first.click()
        play.click()
        pause.wait_for()
        page.clock.fast_forward(1500)
        assert_frame(page, frames, 1, colors)
        pause.click()
        page.clock.fast_forward(3000)
        assert_frame(page, frames, 1, colors)
        cells.nth(len(frames) - 2).click()
        play.click()
        page.clock.fast_forward(1500)
        assert_frame(page, frames, len(frames) - 1, colors)
        assert play.is_disabled(), "playback must stop at the final frame"
        page.clock.fast_forward(3000)
        assert_frame(page, frames, len(frames) - 1, colors)

        # Open the costliest decision, then return to the same frame and focus.
        pick = max(range(len(grades)), key=lambda i: (grades[i]["verdict"] != "best", grades[i]["ev_loss"]))
        cells.nth(pick).click()
        shown = assert_frame(page, frames, pick, colors)
        explain.click()
        current = page.locator(".current-decision .verdict")
        current.wait_for(timeout=LONG)
        title = current.locator(".text").text_content()
        assert title == f"第 {pick + 1} 手，{shown['choice']}", ("opened the wrong decision", title)
        assert verdict_class(grades[pick]) in current.get_attribute("class").split(), current.get_attribute("class")
        if grades[pick]["kind"] == "discard":
            chosen = grades[pick]["chosen_tile"]
            cut = page.locator(".seat--bottom .handrow > .tile.cut")
            assert cut.count() == 1 and int(cut.get_attribute("data-tile")) == chosen, "replayed hand lost the cut tile"
            assert page.locator(".seat--bottom .tile-score").count() > 0, "replayed hand lost its score badges"
        if shots:
            page.screenshot(path=str(shots / "review-open.png"), full_page=True)
        page.get_by_role("button", name="‹ 回結果").click()
        assert_frame(page, frames, pick, colors)
        assert explain.evaluate("button => button === document.activeElement"), "back should restore focus to 看解說"

        page.reload()
        page.locator(".outcome").wait_for(timeout=LONG)
        assert_review(page, grades, "after reload")
        assert_frame(page, frames, 0, colors)

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            cells.last.click()
            assert_frame(page, frames, len(frames) - 1, colors)
            if shots:
                page.screenshot(path=str(shots / f"review-{width}.png"), full_page=True)
                page.locator(".outcome").screenshot(path=str(shots / f"outcome-{width}.png"))
            wide = page.evaluate(VIEWPORT_PROBLEMS)
            assert not wide, (width, height, wide)
            print(f"{width}x{height}: PASS (no horizontal overflow)", flush=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#rotate-prompt").wait_for(state="visible")
        page.set_viewport_size({"width": 844, "height": 390})
        page.locator("#rotate-prompt").wait_for(state="hidden")
        assert not errors, errors
        verdicts = " ".join(cell["state"] for cell in review["cells"])
        print(f"seed{SEED}: PASS {len(grades)} decisions ({'/'.join(sorted(kinds))}) "
              f"score {review['stats']['score']} loss {review['stats']['loss']} · {verdicts}", flush=True)
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--shots", type=Path, default=None, help="directory for screenshots")
    args = parser.parse_args()
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{args.port}"
    wait_for_server(url, None)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run(browser, url, args.shots)
        finally:
            browser.close()
    print("Hand review: PASS (1 live hand, 4 viewport checks, portrait rotation)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
