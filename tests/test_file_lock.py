"""Tests for file locking utility."""

from pathlib import Path
from codebase_cortex.utils.file_lock import cortex_lock


def test_lock_acquires_on_first_call(tmp_path: Path):
    lock_path = tmp_path / "test.lock"
    with cortex_lock(lock_path) as acquired:
        assert acquired is True
        assert lock_path.exists()


def test_lock_fails_when_already_held(tmp_path: Path):
    lock_path = tmp_path / "test.lock"
    with cortex_lock(lock_path) as outer:
        assert outer is True
        with cortex_lock(lock_path) as inner:
            assert inner is False


def test_lock_releases_after_context(tmp_path: Path):
    lock_path = tmp_path / "test.lock"
    with cortex_lock(lock_path) as first:
        assert first is True
    # Lock should be released — can re-acquire
    with cortex_lock(lock_path) as second:
        assert second is True
