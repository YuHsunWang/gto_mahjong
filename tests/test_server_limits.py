"""Public admission, worker deadlines and trainer lifecycle regression tests."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import api
from server.lifecycle import single_process
from server.limits import Admission, LimitMiddleware, Limits
from taimahjong.analysis import AnalysisContext
from taimahjong.budget import EngineDeadlineExceeded, checkpoint, deadline
from taimahjong.ev import _sample_production_world
from taimahjong.tiles import parse_tiles


pytestmark = pytest.mark.timeout(15)


def limited_app(limits=Limits()):
    app = FastAPI()
    gate = Admission(limits)
    app.add_middleware(LimitMiddleware, admission=gate)
    app.add_exception_handler(EngineDeadlineExceeded, api.engine_timeout)

    @app.get('/api/health')
    async def health():
        return {'status': 'ok'}

    @app.post('/api/work')
    def work():
        return {'ok': True}

    return app, gate


def test_overload_rejected_while_health_stays_responsive():
    app, gate = limited_app(Limits(concurrent=1))
    entered, release = threading.Event(), threading.Event()

    @app.post('/api/block')
    def block():
        entered.set()
        assert release.wait(5)
        return {'ok': True}

    with TestClient(app) as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client.post, '/api/block', json={})
        try:
            assert entered.wait(5)
            full = client.post('/api/work', json={})
            assert full.status_code == 503
            assert full.headers['retry-after']
            assert client.get('/api/health').status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200
        assert gate.active == 0
        assert client.post('/api/work', json={}).status_code == 200


def test_rate_limit_ignores_spoofed_forwarding_header():
    app, gate = limited_app(Limits(requests_per_minute=1))
    with TestClient(app) as client:
        assert client.post('/api/work', json={}).status_code == 200
        assert client.post('/api/work', json={}, headers={'X-Forwarded-For': 'other'}).status_code == 429
        assert client.get('/api/health').status_code == 200
    assert gate.active == 0


def test_client_limit_does_not_grow_or_evict_unexpired_rate_counters(monkeypatch):
    import server.limits as limits_module
    clock = [1.0]
    monkeypatch.setattr(limits_module, 'monotonic', lambda: clock[0])
    gate = Admission(Limits(clients=1, requests_per_minute=1))
    assert gate.enter('a', compute=False) is None
    assert gate.enter('b', compute=False) == 429
    assert gate.enter('a', compute=False) == 429
    assert len(gate.clients) == 1
    clock[0] = 62
    assert gate.enter('b', compute=False) is None


@pytest.mark.parametrize('stream', [False, True])
def test_body_limit_covers_content_length_and_chunked_body(stream):
    app, gate = limited_app(Limits(body_bytes=8))
    with TestClient(app) as client:
        body = iter([b'12345', b'67890']) if stream else b'1234567890'
        assert client.post('/api/work', content=body).status_code == 413
        assert gate.active == 0
        assert client.post('/api/work', json={}).status_code == 200


def test_slow_body_times_out_and_releases_admission():
    app, gate = limited_app(Limits(body_seconds=0.01))
    sent = []

    async def scenario():
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            sent.append(message)
        await app({'type': 'http', 'path': '/api/work', 'method': 'POST',
                   'headers': [], 'client': ('test', 1)}, receive, send)

    asyncio.run(scenario())
    assert sent[0]['status'] == 408
    assert gate.active == 0


def test_worker_stops_at_deadline_and_next_request_can_run():
    app, gate = limited_app(Limits(concurrent=1, compute_seconds=0.02))
    stopped = threading.Event()

    @app.post('/api/spin')
    def spin():
        try:
            while True:
                checkpoint()
        finally:
            stopped.set()

    with TestClient(app) as client:
        assert client.post('/api/spin', json={}).status_code == 504
        assert stopped.is_set()
        assert gate.active == 0
        assert client.post('/api/work', json={}).status_code == 200


def test_disconnected_caller_does_not_release_still_running_work():
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        gate = Admission(Limits(concurrent=1))

        async def worker(scope, receive, send):
            started.set()
            await finish.wait()

        middleware = LimitMiddleware(worker, gate)
        async def receive():
            return {'type': 'http.request', 'body': b'{}'}
        async def send(message):
            pass
        scope = {'type': 'http', 'path': '/api/work', 'method': 'POST',
                 'headers': [], 'client': ('test', 1)}
        caller = asyncio.create_task(middleware(scope, receive, send))
        await started.wait()
        caller.cancel()
        await asyncio.sleep(0)  # Deliver cancellation; worker remains alive.
        assert gate.active == 1
        assert gate.enter('other', compute=True) == 503
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert gate.active == 0
    asyncio.run(scenario())


def test_engine_world_sampling_obeys_request_deadline():
    token = deadline.set(monotonic() - 1)
    try:
        with pytest.raises(EngineDeadlineExceeded):
            _sample_production_world(parse_tiles('123m123p123s11122233z'), (0,)*34, (), 1, None, 1)
    finally:
        deadline.reset(token)
    checkpoint()  # CLI/no-request context was restored.


def test_process_lock_rejects_second_worker(tmp_path, monkeypatch):
    monkeypatch.setenv('MJ_PROCESS_LOCK', str(tmp_path / 'api.lock'))
    with single_process():
        with pytest.raises(RuntimeError, match='one API process'):
            with single_process():
                pytest.fail('second worker acquired the lock')
    with single_process():
        pass


@pytest.fixture
def sessions(monkeypatch):
    api._SESSIONS.clear()
    api._ADMISSION.clients.clear()
    monkeypatch.setattr(api, '_MAX_SESSIONS', 1)
    yield
    for session in api._SESSIONS.values():
        api._close_generator(session)
    api._SESSIONS.clear()


def fake_session():
    closed = []
    def play():
        try:
            yield object()
        finally:
            closed.append(True)
    gen = play()
    return api._TrainerSession(1, 0, 0, gen, next(gen), AnalysisContext()), closed


def test_expired_session_closes_generator_and_frees_capacity(sessions):
    old, closed = fake_session()
    api._store_session('old', old)
    old.last_access -= api._SESSION_TTL + 1
    new, _ = fake_session()
    api._store_session('new', new)
    assert closed == [True]
    assert tuple(api._SESSIONS) == ('new',)
    with pytest.raises(api.HTTPException) as caught:
        api._get_session('old')
    assert caught.value.status_code == 404


def test_busy_session_cannot_expire_or_block_get(sessions):
    session, closed = fake_session()
    api._store_session('busy', session)
    with session.lock:
        session.last_access -= api._SESSION_TTL + 1
        with api._SESSIONS_LOCK:
            api._reap_sessions()
        with pytest.raises(api.HTTPException) as caught:
            api.trainer_get('busy')
        assert caught.value.status_code == 409
        assert not closed


def test_capacity_checked_before_starting_engine(sessions, monkeypatch):
    session, _ = fake_session()
    api._store_session('live', session)
    monkeypatch.setattr(api, 'play_trainer', lambda *a: pytest.fail('engine ran while full'))
    with pytest.raises(api.HTTPException) as caught:
        api.trainer_new(api.TrainerNewRequest(seed=1))
    assert caught.value.status_code == 503
    assert api._get_session('live') is session
    assert api._PENDING_SESSION_CREATES == 0


def test_failed_create_releases_reservation(sessions, monkeypatch):
    def fail(*args):
        raise EngineDeadlineExceeded()
    monkeypatch.setattr(api, 'play_trainer', fail)
    with pytest.raises(EngineDeadlineExceeded):
        api.trainer_new(api.TrainerNewRequest(seed=1))
    assert api._PENDING_SESSION_CREATES == 0
    assert not api._SESSIONS


def test_concurrent_create_reserves_capacity_before_generator_starts(sessions, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def slow_start(*args):
        started.set()
        assert release.wait(5)
        yield object()
    monkeypatch.setattr(api, 'play_trainer', slow_start)
    monkeypatch.setattr(api, '_session_payload', lambda sid, session: {'session_id': sid})
    with ThreadPoolExecutor(1) as pool:
        creating = pool.submit(api.trainer_new, api.TrainerNewRequest(seed=1))
        try:
            assert started.wait(5)
            with pytest.raises(api.HTTPException) as caught:
                api.trainer_new(api.TrainerNewRequest(seed=2))
            assert caught.value.status_code == 503
        finally:
            release.set()
        assert creating.result()['session_id'] in api._SESSIONS
    assert api._PENDING_SESSION_CREATES == 0


def test_deadline_during_generator_advance_invalidates_hand(sessions):
    def play():
        yield object()
        checkpoint()
        yield object()
    gen = play()
    session = api._TrainerSession(1, 0, 0, gen, next(gen), AnalysisContext())
    api._store_session('live', session)
    token = deadline.set(monotonic() - 1)
    try:
        with pytest.raises(EngineDeadlineExceeded):
            with api._session_access('live') as current:
                api._advance_session(current, 0)
    finally:
        deadline.reset(token)
    assert session.failed
    assert session.generator is None
    with pytest.raises(api.HTTPException) as caught:
        api._get_session('live')
    assert caught.value.status_code == 404


def test_completed_summary_does_not_consume_live_capacity(sessions):
    done, closed = fake_session()
    done.completed_at = monotonic()
    api._close_generator(done)
    api._store_session('done', done)
    live, _ = fake_session()
    api._store_session('live', live)
    assert api._get_session('done') is done
    assert api._active_sessions() == 1
    assert closed == [True]


def test_delete_releases_live_generator(sessions):
    session, closed = fake_session()
    api._store_session('live', session)
    with TestClient(api.app) as client:
        assert client.delete('/api/trainer/live').status_code == 200
        assert client.get('/api/trainer/live').status_code == 404
    assert closed == [True]
