"""Forced public table fixture; exercise the production feltEl renderer directly."""
import argparse
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from scripts.check_phone_layout import ROOT, wait_for_server


def fixture():
    def meld(tiles, source, called=None, **extra):
        return dict(tiles=tiles, called_tile=tiles[0] if called is None else called,
                    called_from_seat=source, called_from_discard_number=7, **extra)

    def river(offset):
        return [dict(tile=(i + offset) % 34, origin='tedashi' if i % 2 else 'tsumogiri') for i in range(13)]

    left = [meld([0, 1, 2], 2, 2), meld([9] * 3, 1),
            meld([27] * 4, 0, kong_type='open', concealed=False)]
    right = [meld([18] * 4, 0, kong_type='added', concealed=False),
             dict(tiles=[31] * 4, kong_type='concealed', concealed=True)]
    top = [meld([3, 4, 5], 1, 5)]
    hand = [0] * 34
    for tile in range(17):
        hand[tile] += 1
    return dict(seat=0, hand=hand, drawn_tile=16, own_river=river(0),
                own_melds=[], own_meld_details=[],
                own_kong_details=[], wall_remaining=36, turn=16, draws_remaining=9,
                seat_scores=[0] * 4, opponents=[
                    dict(seat=seat, river=river(seat * 5), melds=[m['tiles'][:3] for m in details],
                         meld_details=[m if len(m['tiles']) == 3 else dict(tiles=m['tiles'][:3]) for m in details],
                         kong_details=[dict(m, tile=m['tiles'][0], kind='kong') for m in details if len(m['tiles']) == 4],
                         hand_count=count, is_dealer=False)
                    for seat, details, count in [(1, right, 10), (2, top, 13), (3, left, 7)]])


CHECK = """() => {
  const problems = [];
  const rect = el => el.getBoundingClientRect();
  const close = (a,b) => Math.abs(a-b) < 1;
  const inside = (a,b) => a.left >= b.left-.5 && a.right <= b.right+.5 && a.top >= b.top-.5 && a.bottom <= b.bottom+.5;
  if (document.documentElement.scrollWidth > innerWidth) problems.push('horizontal overflow');
  const felt = rect(document.querySelector('.felt'));
  const sideTiles = [...document.querySelectorAll('.seat--left .meld-slot > .tile, .seat--right .meld-slot > .tile')];
  for (const tile of sideTiles) {
    if (!inside(rect(tile), felt) || !inside(rect(tile), rect(tile.closest('.seat-band')))) problems.push('clipped side meld');
  }
  for (const side of ['left','right']) {
    const seat = document.querySelector('.seat--'+side);
    for (const group of seat.querySelectorAll('.seat-meld')) {
      const slots = [...group.querySelectorAll('.meld-slot')].map(rect);
      if (!slots.every(b => close(b.left, slots[0].left))) problems.push(side+' meld not vertical');
      for (const slot of group.querySelectorAll('.meld-slot')) {
        const b = rect(slot), called = slot.classList.contains('meld-slot--called');
        if (!slot.classList.contains('meld-slot--stacked') && (called ? b.height <= b.width : b.width <= b.height)) problems.push('called tile orientation');
      }
    }
  }
  for (const name of ['bottom','top','left','right']) {
    const tiles = [...document.querySelectorAll('.river--'+name+' > .tile')].map(rect);
    if (tiles.length < 13) problems.push('short river');
    const side = name === 'left' || name === 'right';
    const axis = side ? 'left' : 'top';
    if (!tiles.slice(0,6).every(b => close(b[axis],tiles[0][axis])) || close(tiles[6][axis],tiles[0][axis]) || close(tiles[12][axis],tiles[6][axis])) problems.push(name+' river not six per row');
    const advance = tiles[6][axis] - tiles[0][axis];
    if ((name === 'left' || name === 'top') ? advance >= 0 : advance <= 0) problems.push(name+' river advances toward wrong seat');
    for (const b of tiles) if (!inside(b,felt)) problems.push(name+' river clipped');
  }
  const stack = document.querySelector('.meld-slot--stacked');
  if (!stack || stack.children.length !== 2 || !inside(rect(stack.children[0]),rect(stack)) || !inside(rect(stack.children[1]),rect(stack))) problems.push('added kong stack');
  if (stack) {
    const [a,b] = [...stack.children].map(rect);
    if (a.left < b.right-.5 && b.left < a.right-.5 && a.top < b.bottom-.5 && b.top < a.bottom-.5) problems.push('stacked kong tiles overlap');
  }
  if (document.querySelectorAll('[data-kong-type="concealed"] .tile-back').length !== 4) problems.push('opponent concealed kong must have four backs');
  if (document.querySelector('[data-kong-type="concealed"] .tile:not(.tile-back) svg')) problems.push('opponent concealed kong leaks a face');
  if ([...document.querySelectorAll('.river > .tile')].some(tile => !['none','normal'].includes(getComputedStyle(tile, '::after').content))) problems.push('live river origin bar');
  const ownTiles = [...document.querySelectorAll('.seat--bottom .handrow > .tile')];
  if (ownTiles.length !== 17 || ownTiles.some(tile => !inside(rect(tile), felt) || !inside(rect(tile), rect(tile.closest('.seat-band'))) || rect(tile).bottom > innerHeight)) problems.push('17-tile hand clipped');
  if (!document.querySelector('.river--bottom .tile:last-child.cut')) problems.push('last discard highlight');
  const center = rect(document.querySelector('.center-box'));
  for (const tile of document.querySelectorAll('.river > .tile')) {
    const b = rect(tile);
    if (b.left < center.right-.5 && center.left < b.right-.5 && b.top < center.bottom-.5 && center.top < b.bottom-.5) problems.push('river overlaps center');
  }
  const hand = rect(document.querySelector('.seat--bottom'));
  const rail = rect(document.querySelector('.review-rail'));
  const hit = (a,b) => a.left < b.right-.5 && b.left < a.right-.5 && a.top < b.bottom-.5 && b.top < a.bottom-.5;
  for (const tile of sideTiles) if (hit(rect(tile),hand) || hit(rect(tile),rail)) problems.push('side meld overlaps hand/coach');
  return problems;
}"""


def check(browser, url, width, height, theme, shots):
    context = browser.new_context(viewport=dict(width=width, height=height), device_scale_factor=3)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.add_init_script(f"localStorage.setItem('mj-table-theme', '{theme}');")
    try:
        page.goto(url + '/#/trainer')
        page.locator('#tr-seed').fill('1')
        page.get_by_role('button', name='開始新局').click()
        page.locator('.felt').wait_for(timeout=60000)
        page.evaluate("""async position => {
          const {feltEl} = await import('/js/table.js');
          document.querySelector('.table-scroll').replaceWith(feltEl(position, {ownRiverHighlight:true}));
        }""", fixture())
        page.wait_for_timeout(350)
        problems = page.evaluate(CHECK) + errors
        shots.mkdir(exist_ok=True)
        page.screenshot(path=str(shots / f'r9-{theme}-table-{width if width == 1280 else str(width) + chr(120) + str(height)}.png'), full_page=True, scale='css')
        if theme == 'A' and width == 1280:
            page.locator('.seat--right .seat-melds').screenshot(path=str(shots / 'r6-A-melds-zoom.png'))
        print(f'Side seats {theme} {width}: {"PASS" if not problems else "FAIL"} console_errors={len(errors)} {problems}', flush=True)
        return not problems
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--shots', type=Path, default=ROOT / '.shots')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    wait_for_server(url, None)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            results = [check(browser, url, width, height, theme, args.shots)
                       for width, height, themes in [(1280,900,'ABCD'), (844,390,'AD'), (667,375,'A'), (740,360,'C')] for theme in themes]
        finally:
            browser.close()
    passed = all(results)
    print(f'Side-seat fixture: {"PASS" if passed else "FAIL"} (8 views; five meld types; four 13-tile rivers; 17-tile hand; concealed privacy; no live bars)', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
