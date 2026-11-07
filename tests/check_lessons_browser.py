"""Optional browser regression: PYTHONPATH=. python3 tests/check_lessons_browser.py."""

import socket
import subprocess
import sys

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, wait_for_server
from taimahjong.lessons import LESSONS


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in ((320, 568), (390, 844), (844, 390), (1440, 900)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    try:
                        page = context.new_page()
                        page.set_default_timeout(10000)
                        errors = []
                        ukeire_calls = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("request", lambda request: ukeire_calls.append(request.url)
                                if "/api/ukeire" in request.url else None)
                        page.goto(url)
                        page.locator('a[href="#/lessons"]').wait_for()
                        # Exercise the shared feedback card, including a fallback
                        # lesson with no displayed concept label.
                        for source in ("label", "jev", None):
                            page.evaluate("""async source => {
                              const { reviewRailEl } = await import('/js/feedback.js');
                              const grade = {
                                verdict: 'mistake', marginal: false, ev_delta: 2,
                                ranking_state: 'clear', ranked: [],
                                best: {discard: 22, net_ev: 3},
                                chosen: {discard: 26, net_ev: 1},
                                mistake_label: source === 'label'
                                  ? {label: 'ignored_danger', confidence: .9} : null,
                                matched_lesson: source
                                  ? {id: 'respect-threat', source, title: '有威脅，先看現物'} : null,
                              };
                              const session = {
                                hands: 0, decisions: 1, qualityScore: null,
                                counts: {best: 0, good: 0, inaccuracy: 0, mistake: 1},
                                unresolved: 0, legacy: 0, avgLossPerHand: null,
                              };
                              document.getElementById('app').replaceChildren(reviewRailEl({grade, session}));
                            }""", source)
                            assert page.locator(".lesson-link").count() == (0 if source is None else 1)
                            if source == "label":
                                assert page.locator(".mistake-label + .lesson-link").count() == 1
                            if source:
                                link = page.get_by_role("link", name="去看這一課：有威脅，先看現物")
                                assert link.get_attribute("href") == "#/lessons/respect-threat"
                                link.click()
                                page.get_by_role("heading", name="有威脅，先看現物", exact=True).wait_for()
                                assert page.get_by_text("你的副露", exact=True).count() == 0
                                assert page.locator(".lesson-tiles").nth(0).locator(".tile").count() == 17
                                assert page.locator(".lesson-river").count() == 4
                                assert page.locator(".lesson-river .note").filter(has_text="已宣告聽牌").count() == 3
                                assert page.locator(".evtable").count() == 0
                                assert not ukeire_calls
                                if width == 390:
                                    page.screenshot(path=f"/tmp/lesson-danger-{source}.png", full_page=True)
                                page.get_by_role("button", name="‹ 教學", exact=True).click()
                                page.locator(".lesson-card").first.wait_for()
                                assert page.locator(".lesson-card").count() == len(LESSONS)
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        # Deep links survive a reload, including the attacking
                        # lesson's non-declared rivers and the efficiency table.
                        page.goto(f"{url}/#/lessons/keep-attacking")
                        page.get_by_role("heading", name="別為安心拆好聽", exact=True).wait_for()
                        page.reload()
                        page.get_by_role("heading", name="別為安心拆好聽", exact=True).wait_for()
                        assert page.locator(".lesson-river .note").filter(has_text="未宣告").count() == 3
                        assert page.locator(".lesson-points p").count() == 3
                        assert page.locator(".evtable").count() == 0
                        assert not ukeire_calls
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.goto(f"{url}/#/lessons/pair-vs-run")
                        page.get_by_role("heading", name="別把順子鎖成雀頭", exact=True).wait_for()
                        page.locator(".evtable .best-row").wait_for()
                        assert "一萬" in page.locator(".evtable .best-row").inner_text()
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        assert not errors, errors
                        print(f"{width}x{height}: PASS feedback label/fallback/no match, deep links, danger rivers, efficiency table", flush=True)
                    finally:
                        context.close()
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
