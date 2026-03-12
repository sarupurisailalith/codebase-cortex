"""Simple file-based locking for concurrent access to FAISS index and MetaIndex."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


@contextmanager
def cortex_lock(lock_path: Path) -> Generator[bool, None, None]:
    """Acquire an exclusive file lock.

    Yields True if lock was acquired, False if already held by another process.
    Non-blocking — does not wait.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield True
    except (BlockingIOError, OSError):
        yield False
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_file.close()
