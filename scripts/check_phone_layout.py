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
PHONES = ((844, 390), (740, 360), (667, 375))
ROUTES = ("quiz", "trainer", "endgame", "attack-defense")


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


def check_page(browser, url, width, height, route, screenshot=None, theme="A"):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    try:
        page.add_init_script(f"Math.random = () => 0; localStorage.setItem('mj-table-theme', '{theme}');")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
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
            return box.left < 0 || box.right > width || box.top < 0 || box.bottom > innerHeight;
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
        assert not page.locator('#rotate-prompt').is_visible()
        rail = page.locator('.review-rail')
        rail.scroll_into_view_if_needed()
        assert rail.is_visible()
        if width <= 844:
            assert rail.bounding_box()['y'] >= page.locator('.felt').bounding_box()['y'] + page.locator('.felt').bounding_box()['height']
        page.evaluate('scrollTo(0, 0)')
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
        passed = passed and not errors
        status = "PASS" if passed else "FAIL"
        print(f"{theme} {width}x{height} #/{route}: {status} "
              f"tiles={result['count']} outside={result['outside']} "
              f"scrollWidth={result['scrollWidth']}"
              + (f" chips={result['chips']} overflowingChips={result['overflowingChips']} "
                 f"sideChildren={result['sideChildren']} hiddenSideChildren={result['hiddenSideChildren']} clippedSideChildren={result['clippedSideChildren']} "
                 f"topBacks={result['topBacks']} topInside={result['topInside']}"
                 if route == "trainer" else ""), flush=True)
        return passed
    finally:
        context.close()


def check_portrait(browser, url, theme):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.add_init_script(f"Math.random = () => 0; localStorage.setItem('mj-table-theme', '{theme}');")
        page.goto(url)
        assert not page.locator('#rotate-prompt').is_visible()
        assert not page.locator('#app').evaluate('(app) => app.inert')
        for route in ROUTES:
            page.goto(f'{url}/#/{route}')
            if route == 'trainer':
                page.locator('#tr-seed').fill('1')
                page.get_by_role('button', name='開始新局').click()
            page.locator('.felt').wait_for(state='attached', timeout=60000)
            page.locator('#rotate-prompt').wait_for()
            assert page.locator('#app').evaluate('(app) => app.inert')
            assert page.evaluate("document.elementFromPoint(195,422).closest('#rotate-prompt') !== null")
            if theme == 'A' and route == 'trainer':
                page.screenshot(path=str(ROOT / '.shots/r9-A-portrait-prompt-390.png'))
            page.set_viewport_size({'width': 844, 'height': 390})
            page.locator('#rotate-prompt').wait_for(state='hidden')
            assert not page.locator('#app').evaluate('(app) => app.inert')
            page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(url + '/#/')
        page.locator('.lobby').wait_for()
        assert not page.locator('#rotate-prompt').is_visible()
        print(f'{theme} portrait: PASS (4 table prompts, rotate recovery, lobby usable)', flush=True)
        return True
    finally:
        context.close()


def check_orientation_requests(browser, url):
    for failure in ('none', 'lock', 'fullscreen', 'late'):
        context = browser.new_context(viewport={'width': 844, 'height': 390}, has_touch=True)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""failure => {
          window.orientationCalls = [];
          let fullscreen = false;
          Object.defineProperty(document, 'fullscreenElement', {get: () => fullscreen ? document.documentElement : null});
          Element.prototype.requestFullscreen = async () => {
            orientationCalls.push('fullscreen');
            if (failure === 'fullscreen') throw Error('denied');
            if (failure === 'late') await new Promise(resolve => window.resolveFullscreen = resolve);
            fullscreen = true;
          };
          document.exitFullscreen = async () => {orientationCalls.push('exit'); fullscreen = false;};
          screen.orientation.lock = async orientation => {
            orientationCalls.push(orientation);
            if (failure === 'lock') throw Error('unsupported');
          };
          screen.orientation.unlock = () => orientationCalls.push('unlock');
        }""".replace('failure => {', f'(() => {{ const failure = {failure!r};') + ')();')
        try:
            page.goto(url)
            assert not errors, errors
            assert page.evaluate("matchMedia('(pointer: coarse)').matches")
            page.evaluate('orientationCalls.length = 0')
            page.locator('.lobby a[href="#/trainer"]').click()
            page.locator('#tr-seed').wait_for()
            if failure != 'late':
                page.wait_for_function("orientationCalls.includes('fullscreen')")
                if failure != 'fullscreen':
                    page.wait_for_function("orientationCalls.includes('landscape')")
            page.get_by_role('link', name='‹ 大廳').click()
            page.locator('.lobby').wait_for()
            if failure == 'late':
                page.evaluate('resolveFullscreen()')
                page.wait_for_function("orientationCalls.includes('exit')")
            assert not page.evaluate('!!document.fullscreenElement')
            assert not errors, errors
            calls = page.evaluate('orientationCalls')
            assert calls[0] == 'fullscreen', calls
            if failure in ('none', 'lock'):
                assert calls[:2] == ['fullscreen', 'landscape'] and 'exit' in calls, calls
            print(f'Orientation {failure}: PASS (tap, landscape request, leave cleanup, silent rejection)', flush=True)
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
                check_orientation_requests(browser, url)
                for theme in "ABCD":
                    for width, height in PHONES:
                        for route in ROUTES:
                            shot = None
                            if args.screenshot_prefix and (width, height, route) == (844, 390, "quiz"):
                                shot = Path(f"{args.screenshot_prefix}-{theme}-844x390-quiz.png")
                            try:
                                passed = check_page(browser, url, width, height, route, shot, theme) and passed
                            except Exception as error:
                                print(f"{theme} {width}x{height} #/{route}: FAIL {error}", flush=True)
                                passed = False
                for theme in "ABCD":
                    passed = check_portrait(browser, url, theme) and passed
                if args.screenshot_prefix:
                    passed = check_page(browser, url, 1440, 900, "quiz",
                                        Path(f"{args.screenshot_prefix}-1440x900-quiz.png")) and passed
            finally:
                browser.close()
        print(f"Phone themes: {'PASS' if passed else 'FAIL'} (4 themes × 3 landscape viewports × 4 table routes; portrait prompt + lobby)", flush=True)
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
