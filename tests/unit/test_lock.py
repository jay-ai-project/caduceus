"""U4 — InstanceLock acquire/reclaim/release."""

from __future__ import annotations

import os

import pytest

from caduceus.daemon.lock import AlreadyRunning, InstanceLock


def test_acquire_and_release(tmp_path):
    lock = InstanceLock(tmp_path / "caduceus.pid")
    lock.acquire()
    assert lock.read_pid() == os.getpid()
    assert lock.is_running() is True
    lock.release()
    assert lock.read_pid() is None


def test_double_acquire_same_process_is_blocked(tmp_path):
    p = tmp_path / "caduceus.pid"
    a = InstanceLock(p)
    a.acquire()
    b = InstanceLock(p)
    with pytest.raises(AlreadyRunning):
        b.acquire()  # our own live pid holds it
    a.release()


def test_stale_lock_reclaimed(tmp_path):
    p = tmp_path / "caduceus.pid"
    # write a pid that is almost certainly dead
    p.write_text("999999", encoding="utf-8")
    lock = InstanceLock(p)
    assert lock.is_running() is False
    lock.acquire()  # reclaims stale
    assert lock.read_pid() == os.getpid()
    lock.release()


def test_context_manager(tmp_path):
    p = tmp_path / "caduceus.pid"
    with InstanceLock(p) as lock:
        assert lock.read_pid() == os.getpid()
    assert not p.exists()
