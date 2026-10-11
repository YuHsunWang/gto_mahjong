"""Cooperative deadlines for bounded engine work; CLI callers are unlimited.

The API sets one deadline for the whole request. Checkpoints run in the worker
thread, so returning/cancelling a browser request does not release admission
while abandoned simulation work is still running.
"""

from contextvars import ContextVar
from time import monotonic


deadline: ContextVar[float | None] = ContextVar("engine_deadline", default=None)


class EngineDeadlineExceeded(Exception):
    """The engine stopped at a safe checkpoint after exhausting its budget."""


def checkpoint() -> None:
    limit = deadline.get()
    if limit is not None and monotonic() >= limit:
        raise EngineDeadlineExceeded("calculation exceeded its time budget")
