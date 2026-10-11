"""Opt-in Chromium journeys. Reduced engine budgets test flow, not latency.

MJ_BROWSER_TESTS=1 python -m pytest -q tests/test_browser_recovery.py
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


pytestmark = [
    pytest.mark.skipif(os.environ.get('MJ_BROWSER_TESTS') != '1', reason='opt-in browser suite'),
    pytest.mark.timeout(90),
]


@pytest.fixture(scope='module')
def web_server(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    tmp = tmp_path_factory.mktemp('browser-server')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'MJ_PROCESS_LOCK': str(tmp / 'server.lock'), 'MJ_REQUESTS_PER_MINUTE': '600'}
    # Do not put reduced budgets in the production launcher.
    code = (
        'from taimahjong import quiz; '
        'quiz.EV_SIMS=2; quiz.REFINE_SIMS=3; quiz.ESCALATE_SIMS=4; '
        'import uvicorn; '
        f'uvicorn.run("server.api:app", host="127.0.0.1", port={port}, log_level="warning")'
    )
    with (tmp / 'server.log').open('w+') as log:
        process = subprocess.Popen([sys.executable, '-c', code], cwd=root, env=env, stdout=log, stderr=log)
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    if httpx.get(url + '/api/health', timeout=1, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                time.sleep(0.1)
            else:
                pytest.fail('browser test server did not start')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        yield page
        assert not errors
        context.close()
        browser.close()


def create_hand(url):
    result = httpx.post(url + '/api/trainer/new', json={'seed': 1}, timeout=30, trust_env=False)
    result.raise_for_status()
    return result.json()


@pytest.mark.parametrize('status', [404, 409, 503])
def test_resume_preserves_transient_session_and_recovers(page, web_server, status):
    from playwright.sync_api import expect
    state = create_hand(web_server)
    sid = state['session_id']
    page.add_init_script(f'sessionStorage.setItem("mj-trainer-sid", {json.dumps(sid)})')
    path = f'**/api/trainer/{sid}'
    page.route(path, lambda route: route.fulfill(status=status, json={'detail': 'injected failure'}))
    page.goto(web_server + '/#/trainer')
    if status == 404:
        expect(page.get_by_role('button', name='開始新局')).to_be_visible()
        assert page.evaluate('sessionStorage.getItem("mj-trainer-sid")') is None
    else:
        expect(page.get_by_role('button', name='重新讀取牌局')).to_be_visible()
        assert page.evaluate('sessionStorage.getItem("mj-trainer-sid")') == sid
        page.unroute(path)
        page.get_by_role('button', name='重新讀取牌局').click()
        expect(page.locator('.handrow button.tile').first).to_be_visible()
    httpx.delete(web_server + f'/api/trainer/{sid}', trust_env=False)


def test_lost_act_response_resyncs_without_duplicate_score(page, web_server):
    from playwright.sync_api import expect
    state = create_hand(web_server)
    sid = state['session_id']
    assert state['decision']['type'] == 'discard'
    page.add_init_script(f'sessionStorage.setItem("mj-trainer-sid", {json.dumps(sid)})')
    calls = []

    def lose_response(route):
        response = route.fetch(timeout=60000)
        assert response.ok
        calls.append(response.json())
        route.abort('failed')  # Backend committed, browser never got its reply.

    page.route(f'**/api/trainer/{sid}/act', lose_response)
    page.goto(web_server + '/#/trainer')
    tile = page.locator('.handrow button.tile').first
    tile.click()
    tile.click()
    expect(page.get_by_role('button', name=re.compile('下一手|看結果'))).to_be_visible(timeout=60000)
    assert len(calls) == 1
    assert calls[0]['step'] == state['step'] + 1
    count = "JSON.parse(localStorage.getItem('mj-stats-v3')).trainer['3-1'].filter(e => e.type === 'grade').length"
    assert page.evaluate(count) == 1
    page.reload()
    expect(page.get_by_text('載入中…', exact=True)).to_be_hidden()
    assert page.evaluate(count) == 1
    httpx.delete(web_server + f'/api/trainer/{sid}', trust_env=False)
