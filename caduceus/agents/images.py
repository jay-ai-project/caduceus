"""ImageBuilder — ensure the agent image is present (idempotent).

U8: caduceus uses the **official** `nousresearch/hermes-agent` image (pinned to a version
tag) rather than a hand-maintained Dockerfile. It ships the full agent toolchain (Python,
Node + Playwright/Chromium, ffmpeg, git, ripgrep, Docker CLI, ssh, ...) and runs the hermes
API server via `gateway run`. `ensure_image` `docker pull`s it if absent.
"""

from __future__ import annotations

import asyncio

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger
from caduceus.common.util import make_emit

log = get_logger("caduceus.images")

#: Official image, pinned to a version tag (parity with hermes 0.17.0 / v2026.6.19).
DEFAULT_TAG = "nousresearch/hermes-agent:v2026.6.19"


class ImageBuilder:
    def __init__(self, docker_bin: str = "docker"):
        self._docker = docker_bin

    async def image_exists(self, tag: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self._docker, "image", "inspect", tag,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=30.0)
        return rc == 0

    async def ensure_image(self, tag: str = DEFAULT_TAG, progress=None) -> str:
        """Pull the image if absent; return the tag.

        `progress(phase, detail="")` (optional, sync or async) is called for the slow pull."""
        _emit = make_emit(progress)

        if await self.image_exists(tag):
            return tag
        log.info("pulling agent image %s", tag)
        await _emit("pulling image", "first run, this can take a while (large image)")
        proc = await asyncio.create_subprocess_exec(
            self._docker, "pull", tag,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=1800.0)
        if proc.returncode != 0:
            raise upstream_error(f"docker pull failed: {out.decode('utf-8', 'replace')[-400:]}")
        return tag
