"""ImageBuilder — build/ensure the hermes agent image (idempotent).

The real build runs `docker build`; the image is then **loaded into sbx's own
runtime image store** (`docker save | sbx template load`), because sbx keeps a
separate store from the host Docker daemon — a host-built tag is otherwise
invisible to `sbx create -t` and fails with "pull failed" (Build & Test, Finding
D, 2026-06-30). The Dockerfile lives at `images/hermes/Dockerfile`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.images")

DEFAULT_TAG = "caduceus/hermes:0.17.0"
DEFAULT_HERMES_VERSION = "0.17.0"
#: hermes-agent git tags are date-based; v2026.6.19 == release 0.17.0 (host parity).
DEFAULT_HERMES_GIT_REF = "v2026.6.19"


class ImageBuilder:
    def __init__(self, context_dir: str | Path, docker_bin: str = "docker", sbx_bin: str = "sbx"):
        self._context = Path(context_dir)
        self._docker = docker_bin
        self._sbx = sbx_bin

    async def image_exists(self, tag: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self._docker, "image", "inspect", tag,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=30.0)
        return rc == 0

    async def ensure_image(self, tag: str = DEFAULT_TAG, hermes_version: str = DEFAULT_HERMES_VERSION,
                           git_ref: str = DEFAULT_HERMES_GIT_REF, progress=None) -> str:
        """Build the image (if absent) and ensure it is in sbx's image store. Returns the tag.

        `progress(phase, detail="")` (optional) is called for the slow steps."""
        async def _emit(phase: str, detail: str = "") -> None:
            if progress is None:
                return
            res = progress(phase, detail)
            if hasattr(res, "__await__"):
                await res

        if not await self.image_exists(tag):
            log.info("building hermes image %s (version %s, ref %s)", tag, hermes_version, git_ref)
            await _emit("building image", "first run, may take a few minutes")
            proc = await asyncio.create_subprocess_exec(
                self._docker, "build", "-t", tag,
                "--build-arg", f"HERMES_VERSION={hermes_version}",
                "--build-arg", f"HERMES_GIT_REF={git_ref}",
                str(self._context),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=1800.0)
            if proc.returncode != 0:
                raise upstream_error(f"docker build failed: {out.decode('utf-8', 'replace')[-400:]}")
        await self._ensure_in_sbx(tag, _emit)
        return tag

    async def _ensure_in_sbx(self, tag: str, emit=None) -> None:
        """Bridge a host-Docker image into sbx's separate image store (Finding D)."""
        if await self._in_sbx(tag):
            return
        if emit is not None:
            await emit("loading image into sandbox runtime")
        tar = tempfile.mktemp(suffix=".tar")  # noqa: S306 — local, short-lived
        try:
            await self._run_checked(self._docker, "save", tag, "-o", tar, timeout=300.0,
                                    what="docker save")
            await self._run_checked(self._sbx, "template", "load", tar, timeout=300.0,
                                    what="sbx template load")
        finally:
            try:
                os.remove(tar)
            except OSError:
                pass

    async def _in_sbx(self, tag: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self._sbx, "template", "ls",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            return False
        repo, _, ver = tag.rpartition(":")
        text = out.decode("utf-8", "replace")
        return repo in text and (not ver or ver in text)

    async def _run_checked(self, *args: str, timeout: float, what: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            raise upstream_error(f"{what} failed: {out.decode('utf-8', 'replace')[-300:]}")
