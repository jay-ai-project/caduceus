"""InstanceLock — single daemon per host (BR-G3).

A pid file in `~/.caduceus`. Acquiring fails if a *live* pid already holds it; a
stale lock (the recorded pid is dead) is reclaimed. No third-party deps.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class AlreadyRunning(Exception):
    def __init__(self, pid: int):
        super().__init__(f"caduceus daemon already running (pid {pid})")
        self.pid = pid


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    return True


class InstanceLock:
    def __init__(self, path: "str | os.PathLike"):
        self._path = Path(path)
        self._acquired = False

    def read_pid(self) -> Optional[int]:
        try:
            return int(self._path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        pid = self.read_pid()
        return pid is not None and _pid_alive(pid)

    def acquire(self) -> None:
        pid = self.read_pid()
        if pid is not None and _pid_alive(pid):
            raise AlreadyRunning(pid)
        # stale or absent → claim it
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._path.parent, 0o700)
        except OSError:
            pass
        self._path.write_text(str(os.getpid()), encoding="utf-8")
        self._acquired = True

    def release(self) -> None:
        if self._acquired and self.read_pid() == os.getpid():
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
        self._acquired = False

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
