"""Check that phone hands, seat chips and opponent backs fit the table."""

import argparse
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PHONES = ((320, 568), (375, 812), (390, 844))
ROUTES = ("quiz", "trainer", "endgame")


def wait_for_server(url, process):
    for _ in range(100):
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"server did not respond at {url}")


def check_page(browser, url, width, height, route, screenshot=None):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    try:
        page.add_init_script("Math.random = () => 0")
        page.goto(f"{url}/#/" + route)
        if route == "trainer":
            page.locator("#tr-seed").fill("1")
            page.get_by_role("button", name="開始新局").click()
        hand = page.locator(".seat--bottom .handrow button.tile")
        hand.first.wait_for(timeout=60000)
        result = page.evaluate("""() => {
          const width = window.innerWidth;
          const tiles = [...document.querySelectorAll('.seat--bottom .handrow button.tile')];
          const outside = tiles.filter(tile => {
            const box = tile.getBoundingClientRect();
            return box.left < 0 || box.right > width;
          });
          const chips = [...document.querySelectorAll('.felt .seat-identity')];
          const overflowingChips = chips.filter(chip => chip.scrollWidth > chip.clientWidth);
          const sideChips = [...document.querySelectorAll(
            '.seat--left .seat-identity, .seat--right .seat-identity')];
          const sideChildren = sideChips.flatMap(chip => [...chip.children]);
          const hiddenSideChildren = sideChildren.filter(child => {
            const box = child.getBoundingClientRect();
            const style = getComputedStyle(child);
            return box.width <= 0 || box.height <= 0 || style.display === 'none'
              || style.visibility === 'hidden' || style.visibility === 'collapse'
              || !child.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
          });
          const inside = (box, outer) => box.left >= outer.left && box.right <= outer.right
            && box.top >= outer.top && box.bottom <= outer.bottom;
          const clippedSideChildren = sideChildren.filter(child => {
            const box = child.getBoundingClientRect();
            const chip = child.parentElement.getBoundingClientRect();
            const seat = child.closest('.seat-band').getBoundingClientRect();
            return !inside(box, chip) || !inside(box, seat);
          });
          const felt = document.querySelector('.felt').getBoundingClientRect();
          const topRow = document.querySelector('.seat--top .concealed-hand');
          const topBox = topRow?.getBoundingClientRect();
          const backs = [...(topRow?.querySelectorAll('.tile-back') || [])];
          const insideFelt = box => box.left >= felt.left && box.right <= felt.right
            && box.top >= felt.top && box.bottom <= felt.bottom;
          const topInside = !!topBox && backs.length > 0 && insideFelt(topBox)
            && backs.every(back => insideFelt(back.getBoundingClientRect()));
          return {count: tiles.length, outside: outside.length,
            scrollWidth: document.documentElement.scrollWidth,
            chips: chips.length, overflowingChips: overflowingChips.length,
            sideChips: sideChips.length, sideChildren: sideChildren.length,
            hiddenSideChildren: hiddenSideChildren.length,
            clippedSideChildren: clippedSideChildren.length,
            topBacks: backs.length, topInside};
        }""")
        if screenshot:
            page.screenshot(path=str(screenshot), full_page=True)
        passed = result["count"] > 0 and result["outside"] == 0 and result["scrollWidth"] <= width
        if route == "trainer":
            passed = (passed and result["chips"] == 4
                      and result["overflowingChips"] == 0
                      and result["sideChips"] == 2 and result["sideChildren"] > 0
                      and result["hiddenSideChildren"] == 0
                      and result["clippedSideChildren"] == 0
                      and result["topBacks"] == 16 and result["topInside"])
        status = "PASS" if passed else "FAIL"
        print(f"{width}x{height} #/{route}: {status} "
              f"tiles={result['count']} outside={result['outside']} "
              f"scrollWidth={result['scrollWidth']}"
              + (f" chips={result['chips']} overflowingChips={result['overflowingChips']} "
                 f"sideChildren={result['sideChildren']} hiddenSideChildren={result['hiddenSideChildren']} clippedSideChildren={result['clippedSideChildren']} "
                 f"topBacks={result['topBacks']} topInside={result['topInside']}"
                 if route == "trainer" else ""), flush=True)
        return passed
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--expect-server", action="store_true", help="use a running server")
    parser.add_argument("--screenshot-prefix", type=Path, help="save quiz phone and desktop screenshots")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    process = None
    try:
        if not args.expect_server:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", str(args.port)],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                passed = True
                for width, height in PHONES:
                    for route in ROUTES:
                        shot = None
                        if args.screenshot_prefix and (width, height, route) == (390, 844, "quiz"):
                            shot = Path(f"{args.screenshot_prefix}-390x844-quiz.png")
                        try:
                            passed = check_page(browser, url, width, height, route, shot) and passed
                        except Exception as error:
                            print(f"{width}x{height} #/{route}: FAIL {error}", flush=True)
                            passed = False
                if args.screenshot_prefix:
                    passed = check_page(browser, url, 1440, 900, "quiz",
                                        Path(f"{args.screenshot_prefix}-1440x900-quiz.png")) and passed
            finally:
                browser.close()
        return 0 if passed else 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    sys.exit(main())
