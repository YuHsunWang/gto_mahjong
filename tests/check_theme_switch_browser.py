"""Exercise table themes, first-paint persistence, contrast and shared surfaces.

PYTHONPATH=. python3 tests/check_theme_switch_browser.py
The real trainer supplies the feedback and result; no game state is fabricated.
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from scripts.check_phone_layout import ROOT, wait_for_server
from check_hand_review_browser import play_hand
from check_tile_score_browser import LAYOUT_PROBLEMS

SHOTS = ROOT / '.shots'


def contrast(a, b):
    def luminance(color):
        values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * w for v, w in zip(values, (.2126, .7152, .0722)))
    x, y = sorted((luminance(a), luminance(b)))
    return (y + .05) / (x + .05)


def audit_tokens(page):
    tokens = page.evaluate("""() => {
      const style = getComputedStyle(document.documentElement);
      return Object.fromEntries([...style].filter(k => k.startsWith('--')).map(k => [k.slice(2), style.getPropertyValue(k).trim()]));
    }""")
    surfaces = ['page', 'bg', 'felt-0', 'felt-1', 'felt-2', 'panel', 'lacquer']
    groups = {
        'body': [(ink, surface) for ink in ['ink', 'ink-dim', 'ink-faint', 'focus', 'gold-edge'] for surface in surfaces],
        'rail': [('wood-ink', s) for s in ['wood-hi', 'wood-lo', 'panel']] + [('ink', 'wood-hi')],
        'tile labels': [('mode-ink', 'bone'), ('mode-red', 'bone'), ('bone', 'tool-red'), ('bone', 'tool-blue')],
        'verdict/score': [(ink, q) for ink in ['#14101a', '#241b32', 'badge-ink'] for q in ['q-best', 'q-correct', 'q-inaccuracy', 'q-wrong', 'q-unresolved']]
                         + [('q-best', 'badge-surface'), ('#f0a0a0', 'badge-surface'), ('#9fc0f0', 'badge-surface'), ('#ffffff', 'red'), ('#ffffff', '#765bbe')],
        'actions': [(ink, 'gold') for ink in ['#241300', '#1d1608', '#2b1900']],
        'result': [(ink, surface) for ink in ['win-ink', 'lose-ink'] for surface in ['felt-0', 'felt-1', 'felt-2']],
    }
    result = {}
    for group, pairs in groups.items():
        values = [(contrast(tokens.get(a, a), tokens.get(b, b)), a, b) for a, b in pairs]
        minimum = min(values)
        threshold = 3 if group == 'result' else 4.5
        assert minimum[0] >= threshold, (page.locator('html').get_attribute('data-table-theme'), group, minimum)
        result[group] = round(minimum[0], 2)
    return result


def set_theme(page, theme):
    # The control's instant switch and storage path are exercised below. Use
    # that same root attribute to inspect identical, still-mounted game states.
    page.evaluate('(theme) => document.documentElement.dataset.tableTheme = theme', theme)


def snapshot(page, theme, name, width):
    page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 900})
    set_theme(page, theme)
    page.screenshot(path=str(SHOTS / f'r4-{theme}-{name}-{width}.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def run(browser, url):
    errors = []
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    # Capture the attribute when the parser reaches the stylesheet, before
    # either app modules or the tile renderer can set it.
    page.add_init_script("""new MutationObserver(() => {
      if (document.querySelector('link[rel="stylesheet"]') && !window.themeBeforeCSS)
        window.themeBeforeCSS = document.documentElement.dataset.tableTheme;
    }).observe(document, {subtree: true, childList: true});""")
    page.goto(url)
    select = page.get_by_role('combobox', name='牌桌風格', exact=True)
    assert select.input_value() == 'A'
    assert page.evaluate('window.themeBeforeCSS') == 'A'
    # Native select: Tab reaches it; arrow keys change the theme, with a ring.
    for _ in range(12):
        page.keyboard.press('Tab')
        if select.evaluate('(el) => el === document.activeElement'):
            break
    assert select.evaluate('(el) => el === document.activeElement')
    assert select.evaluate('(el) => parseFloat(getComputedStyle(el).outlineWidth) >= 2')
    page.keyboard.press('ArrowDown')
    assert select.input_value() == 'B'
    assert page.locator('html').get_attribute('data-table-theme') == 'B'
    rows = {}
    for theme in 'ABCD':
        select.select_option(theme)
        assert page.locator('html').get_attribute('data-table-theme') == theme
        assert page.evaluate("localStorage.getItem('mj-table-theme')") == theme
        page.reload()
        assert select.input_value() == theme
        assert page.evaluate('window.themeBeforeCSS') == theme
        rows[theme] = audit_tokens(page)
        # Match the exact approved material study, including existing tile CSS.
        palette = page.evaluate("""async () => {
          const {TILE_THEMES} = await import('/js/tile-faces.js');
          const t = TILE_THEMES.find(t => t.id === document.documentElement.dataset.tableTheme);
          const s = getComputedStyle(document.documentElement);
          return ['page', 'felt-0', 'felt-1', 'felt-2', 'wood', 'wood-hi', 'bone', 'tile-back'].every((k, i) =>
            s.getPropertyValue('--' + k).trim().toLowerCase() === [t.page, t.feltLo, t.felt, t.feltHi, t.rail, t.railHi, t.face, t.back][i].toLowerCase());
        }""")
        assert palette, theme
        snapshot(page, theme, 'lobby', 1280)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert select.is_visible()
        assert select.bounding_box()['x'] + select.bounding_box()['width'] <= 390
        page.screenshot(path=str(SHOTS / f'r4-{theme}-lobby-390.png'), full_page=True)
    # Invalid persisted choices and read/write failures must fall back silently.
    page.evaluate("localStorage.setItem('mj-table-theme', 'invalid')")
    page.reload()
    assert select.input_value() == 'A'
    page.evaluate("""() => {
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function(k, v) { if (k === 'mj-table-theme') throw Error('blocked'); return set.call(this, k, v); };
    }""")
    select.select_option('D')
    assert select.input_value() == 'A'
    page.add_init_script("""const get = Storage.prototype.getItem;
      Storage.prototype.getItem = function(k) { if (k === 'mj-table-theme') throw Error('blocked'); return get.call(this, k); };""")
    page.reload()
    assert select.input_value() == 'A'
    blocked = context.new_page()
    blocked.on('pageerror', lambda error: errors.append(str(error)))
    blocked.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    blocked.add_init_script("Storage.prototype.getItem = Storage.prototype.setItem = () => { throw Error('blocked'); };")
    blocked.goto(url)
    blocked_select = blocked.get_by_role('combobox', name='牌桌風格', exact=True)
    assert blocked_select.input_value() == 'A'
    blocked_select.select_option('D')
    assert blocked_select.input_value() == 'A'
    blocked.close()
    # One real hand supplies a mid-hand discard, coach feedback and result.
    page.evaluate("localStorage.setItem('mj-onetap', '1')")
    page.goto(url + '/#/trainer')
    page.locator('#tr-seed').fill('1')
    page.get_by_role('button', name='開始新局').click()
    page.locator('.seat--bottom .handrow button.tile').first.wait_for(timeout=180000)
    page.locator('.seat--bottom .handrow button.tile').first.click()
    page.locator('.tile-score').first.wait_for(timeout=180000)
    # Advance three turns so the capture has live rivers as well as feedback.
    for _ in range(3):
        page.get_by_role('button', name='▶').click()
        page.locator('.seat--bottom .handrow button.tile, .callbar .call-btn.pass').first.wait_for(timeout=180000)
        passing = page.locator('.callbar .call-btn.pass')
        target = passing.first if passing.count() else page.locator('.seat--bottom .handrow button.tile').first
        target.click()
        page.get_by_role('button', name='▶').wait_for(timeout=180000)
    assert page.locator('.review-rail .current-decision').count()
    for theme in 'ABCD':
        snapshot(page, theme, 'table', 1280)
        assert not page.evaluate(LAYOUT_PROBLEMS)
        snapshot(page, theme, 'table', 390)
        assert not page.evaluate(LAYOUT_PROBLEMS)
    page.get_by_role('button', name='▶').click()
    play_hand(page)
    page.locator('.hand-review').wait_for()
    for theme in 'ABCD':
        snapshot(page, theme, 'result', 1280)
    assert not errors, errors
    (SHOTS / 'r4-contrast.json').write_text(json.dumps(rows, indent=2))
    for theme, row in rows.items():
        print(f'{theme} contrast: ' + ' | '.join(f'{key} {value:.2f}' for key, value in row.items()), flush=True)
    print('Themes: PASS (A/B/C/D; default, instant switch, reload, before CSS, keyboard, accessible name, storage failures; console errors=0)', flush=True)
    context.close()


def main():
    SHOTS.mkdir(exist_ok=True)
    url = 'http://127.0.0.1:8769'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server.api:app', '--host', '127.0.0.1', '--port', '8769'], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_server(url, process)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                run(browser, url)
            finally:
                browser.close()
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == '__main__':
    main()
