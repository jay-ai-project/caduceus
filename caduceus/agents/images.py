"""ImageBuilder — build/ensure the hermes agent image (idempotent).

The real build runs `docker build`; exercised in Build & Test. The Dockerfile
lives at `images/hermes/Dockerfile` (slim hermes-agent, pinned version).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.images")

DEFAULT_TAG = "caduceus/hermes:0.17.0"
DEFAULT_HERMES_VERSION = "0.17.0"


class ImageBuilder:
    def __init__(self, context_dir: str | Path, docker_bin: str = "docker"):
        self._context = Path(context_dir)
        self._docker = docker_bin

    async def image_exists(self, tag: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self._docker, "image", "inspect", tag,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=30.0)
        return rc == 0

    async def ensure_image(self, tag: str = DEFAULT_TAG, hermes_version: str = DEFAULT_HERMES_VERSION) -> str:
        """Build the image if it is not already present. Returns the tag."""
        if await self.image_exists(tag):
            return tag
        log.info("building hermes image %s (version %s)", tag, hermes_version)
        proc = await asyncio.create_subprocess_exec(
            self._docker, "build", "-t", tag,
            "--build-arg", f"HERMES_VERSION={hermes_version}",
            str(self._context),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=1800.0)
        if proc.returncode != 0:
            raise upstream_error(f"docker build failed: {out.decode('utf-8', 'replace')[-400:]}")
        return tag
