"""Optional browser regression: PYTHONPATH=. python tests/check_attack_defense_browser.py.

Uses the existing phone checker and installed Playwright; no new dependency.
"""

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

from scripts.check_phone_layout import ROOT, check_page, wait_for_server


def main():
    url = "http://127.0.0.1:8766"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--host", "127.0.0.1", "--port", "8766"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(url, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in ((320, 568), (375, 812), (390, 844), (844, 390)):
                    assert check_page(browser, url, width, height, "attack-defense")
                # Intersecting sets, disjoint sets, and a non-first attack tie.
                for game, selection, attack, defense in ((1, 2, 33, 33), (3, 4, 29, 26), (5, 6, 14, 1)):
                    context = browser.new_context(viewport={"width": 390, "height": 844})
                    try:
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        seeds = {"game_seed": game, "selection_seed": selection}
                        page.route("**/api/attack-defense/new", lambda route: route.continue_(post_data=json.dumps(seeds)))
                        expected_response = page.request.post(f"{url}/api/attack-defense/grade", data={
                            **seeds, "attack_tile": attack, "defense_tile": defense,
                        })
                        assert expected_response.ok
                        expected = expected_response.json()["grade"]
                        page.goto(f"{url}/#/attack-defense")
                        tiles = page.locator(".seat--bottom .handrow button.tile")
                        tiles.first.wait_for()
                        count = tiles.count()
                        page.locator(
                            f'.seat--bottom .handrow button.tile[data-tile="{attack}"]',
                        ).first.click()
                        page.get_by_text("② 點一張防守牌", exact=False).wait_for()
                        assert tiles.count() == count
                        page.locator(f'.seat--bottom .handrow button.tile[data-tile="{defense}"]').first.click()
                        page.get_by_role("heading", name="作答結果").wait_for()
                        feedback = page.locator(".attack-defense-feedback").inner_text()
                        assert ("這張攻守都對" in feedback) is bool(expected["shared_tiles"])
                        for key, label in (("attack", "攻擊牌"), ("defense", "防守牌")):
                            assert f'{"✓" if expected[key]["correct"] else "✗"} {label}' in feedback
                        assert expected["recommendation"]["verdict"] in feedback
                        assert "這個局面建議打：" in feedback
                        assert f'你選的 {expected["attack"]["ukeire"]} 張' in feedback
                        assert f'最佳攻擊牌 {expected["attack"]["best_ukeire"]} 張' in feedback
                        stats = page.evaluate("JSON.parse(localStorage.getItem('mj-stats-v3'))")
                        assert set(stats) == {"attack-defense"}
                        assert len(stats["attack-defense"]["drill"]) == 2
                        assert [event["v"] for event in stats["attack-defense"]["drill"]] == [
                            "best" if expected[key]["correct"] else "mistake" for key in ("attack", "defense")
                        ]
                        assert not errors, errors
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.evaluate("localStorage.setItem('mj-scheme', '5-2')")
                        page.get_by_role("link", name="‹ 首頁").click()
                        card = page.locator('a.card[href="#/attack-defense"]')
                        assert "已答 2 次選牌" in card.inner_text()
                        print(f"seeds={game}/{selection}: PASS two taps, grading, overlap, recommendation, isolated stats", flush=True)
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
