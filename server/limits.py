"""Bounded admission for the single-process beta server."""

from __future__ import annotations

import asyncio
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from starlette.responses import JSONResponse

from taimahjong.budget import deadline


def positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class Limits:
    concurrent: int = 2
    requests_per_minute: int = 60
    clients: int = 4096
    body_bytes: int = 16384
    body_seconds: float = 5.0
    compute_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> Limits:
        return cls(
            concurrent=positive_int("MJ_MAX_COMPUTE", 2),
            requests_per_minute=positive_int("MJ_REQUESTS_PER_MINUTE", 60),
            compute_seconds=positive_int("MJ_COMPUTE_SECONDS", 60),
        )


class Admission:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.lock = threading.Lock()
        self.active = 0
        self.clients: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def enter(self, client: str, *, compute: bool) -> int | None:
        """No waiting queue: return 429/503 instead of retaining more work."""
        now = monotonic()
        with self.lock:
            # Fixed-window entries are ordered by creation, not access.
            while self.clients and next(iter(self.clients.values()))[0] + 60 <= now:
                self.clients.popitem(last=False)
            if client not in self.clients:
                if len(self.clients) >= self.limits.clients:
                    return 429
                self.clients[client] = (now, 0)
            start, count = self.clients[client]
            if count >= self.limits.requests_per_minute:
                return 429
            self.clients[client] = (start, count + 1)
            if compute:
                if self.active >= self.limits.concurrent:
                    return 503
                self.active += 1
        return None

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


class LimitMiddleware:
    def __init__(self, app, admission: Admission):
        self.app = app
        self.admission = admission

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["path"] == "/api/health":
            await self.app(scope, receive, send)
            return
        compute = scope["method"] == "POST"
        # Uvicorn may resolve a trusted proxy's client IP. Never independently
        # trust arbitrary X-Forwarded-For headers supplied by a caller.
        client = (scope.get("client") or ("unknown", 0))[0]
        status = self.admission.enter(client, compute=compute)
        if status:
            message = "請求過於頻繁，請稍後再試" if status == 429 else "目前運算已滿，請稍後再試"
            await JSONResponse({"detail": message}, status_code=status, headers={"Retry-After": "5"})(scope, receive, send)
            return
        token = None
        try:
            if compute:
                limits = self.admission.limits
                headers = dict(scope.get("headers", []))
                try:
                    size = int(headers.get(b"content-length", b"0"))
                    if size < 0:
                        raise ValueError
                except ValueError:
                    await JSONResponse({"detail": "invalid content length"}, status_code=400)(scope, receive, send)
                    return
                if size > limits.body_bytes:
                    await JSONResponse({"detail": "request body too large"}, status_code=413)(scope, receive, send)
                    return

                async def read_body():
                    body = bytearray()
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return None
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > limits.body_bytes:
                            raise OverflowError
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            return bytes(body)

                try:
                    body = await asyncio.wait_for(read_body(), limits.body_seconds)
                except asyncio.TimeoutError:
                    await JSONResponse({"detail": "request body timed out"}, status_code=408)(scope, receive, send)
                    return
                except OverflowError:
                    await JSONResponse({"detail": "request body too large"}, status_code=413)(scope, receive, send)
                    return
                if body is None:
                    return
                original_receive = receive
                consumed = False

                async def replay_body():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await original_receive()

                receive = replay_body
                token = deadline.set(monotonic() + limits.compute_seconds)
            # Shielding preserves admission on client cancellation until the
            # worker actually stops at its deadline/checkpoint.
            task = asyncio.create_task(self.app(scope, receive, send))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        finally:
            if token is not None:
                deadline.reset(token)
            if compute:
                self.admission.leave()
