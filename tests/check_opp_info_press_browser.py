"""Exercise press-to-reveal opponent details on the production felt renderer."""
import argparse
import sys

from playwright.sync_api import sync_playwright
from scripts.check_phone_layout import wait_for_server

from check_side_seats_browser import RENDER, fixture


def check(browser, url, width, height, phone):
    context = browser.new_context(viewport=dict(width=width, height=height), has_touch=phone, is_mobile=phone)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(url)
        # Mount outside the app so the portrait rotation prompt does not cover the fixture.
        page.evaluate("""() => {
          document.querySelector('#app').replaceChildren();
          const slot = document.createElement('div');
          slot.className = 'table-scroll';
          document.body.append(slot);
        }""")
        position = fixture(own_melds=True)
        position['seat_scores'] = [0, -12, 34, 7]
        # Legacy positions list the concealed kong only in kong_details.
        position['opponents'][0]['melds'].pop()
        position['opponents'][0]['meld_details'].pop()
        position['opponents'][1].update(declared=True, is_dealer=True, dealer_streak=2)
        page.evaluate(RENDER, position)
        own = page.locator('.seat--bottom .seat-identity')
        for label in ('暗手 11', '明牌 6 張', '分數 0'):
            assert own.get_by_text(label, exact=True).is_visible(), f'own tag lost {label}'
        assert own.get_attribute('tabindex') is None, 'own tag became focusable'

        for side, labels in [
            ('left', ('暗手 7', '明牌 10 張', '分數 7')),
            ('top', ('暗手 13', '明牌 3 張', '分數 34')),
            ('right', ('暗手 10', '明牌 8 張', '分數 -12')),
        ]:
            identity = page.locator(f'.seat--{side} .seat-identity')
            items = [identity.get_by_text(label, exact=True) for label in labels]
            assert all(item.count() == 1 for item in items), f'{side} lost detail items'
            assert all(item.is_visible() != phone for item in items), f'{side} wrong default detail visibility'
            assert identity.get_attribute('tabindex') == ('0' if phone else None), f'{side} wrong tab stop'
            if not phone:
                assert identity.locator('.seat-details').evaluate("el => getComputedStyle(el).display") == 'contents'
                continue

            accessible_label = identity.get_attribute('aria-label') or ''
            assert all(label in accessible_label for label in labels), f'{side} missing accessible details'
            identity.hover()
            page.mouse.down()
            assert all(item.is_visible() for item in items), f'{side} details hidden while pressed'
            assert identity.locator('.seat-details').evaluate("el => getComputedStyle(el).position") == 'absolute'
            page.mouse.up()
            assert not any(item.is_visible() for item in items), f'{side} details visible after release'

        top = page.locator('.seat--top .seat-identity')
        for label in ('莊 · 連2', '報聽'):
            assert top.get_by_text(label, exact=True).is_visible(), f'top tag lost {label}'
        if phone:
            details = top.locator('.seat-details')
            top.hover()
            page.mouse.down()
            page.mouse.move(0, 0)
            assert not details.is_visible(), 'details visible after pointer left'
            page.mouse.up()

            top.scroll_into_view_if_needed()
            box = top.bounding_box()
            touch = context.new_cdp_session(page)
            point = dict(x=box['x'] + box['width'] / 2, y=box['y'] + box['height'] / 2)
            touch.send('Input.dispatchTouchEvent', dict(type='touchStart', touchPoints=[point]))
            assert details.is_visible(), 'details hidden during touch hold'
            touch.send('Input.dispatchTouchEvent', dict(type='touchCancel', touchPoints=[]))
            assert not details.is_visible(), 'details visible after touch cancellation'
            assert top.evaluate("el => !el.dispatchEvent(new MouseEvent('contextmenu', {cancelable: true}))"), 'context menu allowed'

            page.locator('#side-fixture').focus()
            page.keyboard.press('Tab')
            assert top.evaluate('el => el === document.activeElement'), 'Tab did not focus opponent tag'
            assert details.is_visible(), 'details hidden during keyboard focus'
            page.keyboard.press('Tab')
            assert not details.is_visible(), 'details visible after focus moved'

        position['seat_scores'] = [None]
        for missing_scores in (position, {key: value for key, value in position.items() if key != 'seat_scores'}):
            page.evaluate(RENDER, missing_scores)
            felt = page.locator('.felt')
            assert felt.locator('.seat-score').count() == 0, 'score item rendered for missing score'
            assert '分數 —' not in felt.text_content(), 'empty score placeholder rendered'
        assert not errors, errors
        print(f'Opponent details {width}x{height}: PASS', flush=True)
        return True
    except AssertionError as error:
        print(f'Opponent details {width}x{height}: FAIL {error}', flush=True)
        return False
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    wait_for_server(url, None)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            results = [check(browser, url, width, height, phone)
                       for width, height, phone in [(390, 844, True), (844, 390, True), (1440, 900, False)]]
        finally:
            browser.close()
    passed = all(results)
    print(f'Opponent details fixture: {"PASS" if passed else "FAIL"} ({sum(results)}/3 views)', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
