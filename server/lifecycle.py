"""Single-process guard: live trainer generators cannot move between workers."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def single_process():
    import fcntl

    path = Path(os.environ.get(
        "MJ_PROCESS_LOCK",
        str(Path(__file__).resolve().parents[1] / "artifacts/work/api.lock"),
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Trainer requires one API process. Use --workers 1 and one replica."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
