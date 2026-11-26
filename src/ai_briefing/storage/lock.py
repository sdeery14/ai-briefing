"""One writer at a time: an operating-system file lock around each job (ADR-002).

The lock is taken on a small file beside the database. It is released by the operating
system if the process dies, so there is no stale lock to clean up and no lease table.
On POSIX this is ``flock``; on Windows, where development happens, it is the equivalent
byte-range lock.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockHeld(RuntimeError):  # noqa: N818 - reads as a statement of fact
    """Another job holds the lock. This one must not run."""


def lock_path(database: str | os.PathLike[str]) -> Path:
    path = Path(database)
    return path.with_name(path.name + ".lock")


if sys.platform == "win32":
    import msvcrt

    def _acquire(handle: int) -> None:
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)

    def _release(handle: int) -> None:
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def job_lock(database: str | os.PathLike[str]) -> Iterator[Path]:
    """Hold the writer lock for the database. Raises :class:`LockHeld` at once if taken."""
    path = lock_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            os.lseek(handle, 0, os.SEEK_SET)
            _acquire(handle)
        except OSError as error:
            raise LockHeld(f"another job holds {path.name}; this job will not run") from error
        try:
            yield path
        finally:
            os.lseek(handle, 0, os.SEEK_SET)
            _release(handle)
    finally:
        os.close(handle)
