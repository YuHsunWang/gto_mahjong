"""Optional browser regression: PYTHONPATH=. python tests/check_deal_setup_browser.py.

The 開局 screen picks the dealer on a seat grid instead of the old `你的座位`
select. The server still takes `human_seat`: how many seats after the dealer
the player sits. Picking the wrong button for that number deals the player a
different seat wind and dealer bonus than the screen shows, so for every
dealer this check asserts the winds drawn on the grid, the human_seat sent,
and that a real hand starts and labels the player's seat the same way.

Uses the existing phone checker and installed Playwright; no new dependency.
"""

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, wait_for_server

# Grid seats in play order from the player (counter-clockwise): 你, 下家, 對家, 上家.
# The dealer is 東 and the winds follow play order from the dealer.
WINDS = {0: "東南西北", 1: "北東南西", 2: "西北東南", 3: "南西北東"}
# The player sits this many seats after the dealer (the old select's values).
HUMAN_SEAT = {0: 0, 1: 3, 2: 2, 3: 1}
SEAT_TAGS = {0: "莊家（你自己做莊）", 1: "莊的下家", 2: "莊的對家", 3: "莊的上家"}


def main():
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
                for dealer in range(4):
                    context = browser.new_context(viewport={"width": 390, "height": 844})
                    try:
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"{url}/#/trainer")
                        seats = [page.locator(f'.seat-grid button[data-seat="{i}"]') for i in range(4)]
                        seats[0].wait_for()
                        assert page.locator('.seat-grid [aria-pressed="true"]').get_attribute("data-seat") == "0"
                        seats[dealer].click()
                        pressed = [seat.get_attribute("aria-pressed") for seat in seats]
                        assert pressed == ["true" if i == dealer else "false" for i in range(4)], pressed
                        winds = "".join(seat.locator(".seat-pick-wind").inner_text() for seat in seats)
                        assert winds == WINDS[dealer], (dealer, winds)
                        page.locator("#tr-seed").fill("1")
                        less = page.get_by_role("button", name="少一次")
                        more = page.get_by_role("button", name="多一次")
                        # aria-disabled at the limits; force the click to prove the clamp holds.
                        less.click(force=True)
                        assert page.locator("#tr-streak").inner_text() == "0"
                        for _ in range(dealer * 3):
                            more.click(force=True)
                        streak = min(8, dealer * 3)
                        assert page.locator("#tr-streak").inner_text() == str(streak)
                        with page.expect_response(lambda r: r.url.endswith("/api/trainer/new"), timeout=180000) as new:
                            page.get_by_role("button", name="開始新局").click()
                        sent = json.loads(new.value.request.post_data)
                        assert sent["seed"] == 1 and sent["human_seat"] == HUMAN_SEAT[dealer], sent
                        assert sent["dealer_streak"] == streak, sent
                        assert new.value.ok and new.value.json()["human_seat"] == HUMAN_SEAT[dealer]
                        page.locator(".seat--bottom .handrow .tile").first.wait_for(timeout=180000)
                        assert SEAT_TAGS[HUMAN_SEAT[dealer]] in page.locator(".topbar .mode-tag").inner_text()
                        assert not errors, errors
                        print(f"dealer={dealer}: PASS winds={winds} human_seat={sent['human_seat']} streak={streak}", flush=True)
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
