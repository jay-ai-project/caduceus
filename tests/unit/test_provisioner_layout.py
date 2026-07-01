"""Storage-layout unit tests for DockerProvisioner (U8-D6).

Assert the *docker argv* the provisioner builds — the FakeProvisioner used elsewhere
can't cover this since it never shells out. Locks in the split introduced in U8-D6:

  * `/opt/data/workspace` is bind-mounted (persistent artifacts) and is the cwd;
  * HERMES_HOME (`/opt/data`) itself is NOT bind-mounted (rides the image anon volume);
  * the container runs as the host UID/GID (so the bind mount is writable both ways);
  * config is injected with `docker cp` into `/opt/data/config.yaml`;
  * delete uses `docker rm -f -v` (wipes the anon HERMES_HOME volume).
"""

from __future__ import annotations

import os

import pytest

from caduceus.agents.provisioner import (
    CONTAINER_DATA,
    CONTAINER_WORKSPACE,
    HERMES_CONFIG_PATH,
    DockerProvisioner,
)


@pytest.fixture
def prov_capture(tmp_path):
    """A DockerProvisioner whose docker calls are captured instead of executed."""
    prov = DockerProvisioner(workspace_root=str(tmp_path))
    calls: list[list[str]] = []

    async def fake_run(*args, timeout=None, stdin=None):
        calls.append(list(args))
        return 0, b"", b""

    async def fake_check(*args, timeout=None, stdin=None):
        calls.append(list(args))
        return b""

    prov._run = fake_run          # type: ignore[method-assign]
    prov._check = fake_check      # type: ignore[method-assign]
    return prov, calls


def _create_argv(calls):
    return next(c for c in calls if c and c[0] == "create")


@pytest.mark.asyncio
async def test_create_mounts_nested_workspace_not_whole_hermes_home(prov_capture):
    prov, calls = prov_capture
    await prov.create("cad-x", "img:1", {"OPENAI_API_KEY": "tok"}, "runc")
    argv = _create_argv(calls)
    ws = prov.workspace_for("cad-x")
    # The nested workspace is bind-mounted and is the working dir…
    assert CONTAINER_WORKSPACE.startswith(CONTAINER_DATA + "/")  # nested under HERMES_HOME
    assert f"{ws}:{CONTAINER_WORKSPACE}" in argv
    assert argv[argv.index("-w") + 1] == CONTAINER_WORKSPACE
    # …but the whole HERMES_HOME is never bind-mounted (no `<host>:/opt/data` volume arg).
    vols = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert all(not v.endswith(f":{CONTAINER_DATA}") for v in vols)


@pytest.mark.asyncio
async def test_create_runs_as_host_uid_gid(prov_capture):
    prov, calls = prov_capture
    await prov.create("cad-x", "img:1", {}, "runc")
    argv = _create_argv(calls)
    env = dict(
        argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-e"
    )
    assert env["HERMES_UID"] == str(os.getuid())
    assert env["HERMES_GID"] == str(os.getgid())
    # We must NOT override the image-default single-path write-safe-root (a colon-joined
    # value would be read as one bogus path and deny every write on the installed hermes).
    assert "HERMES_WRITE_SAFE_ROOT" not in env


@pytest.mark.asyncio
async def test_caller_env_overrides_layout_defaults(prov_capture):
    prov, calls = prov_capture
    await prov.create("cad-x", "img:1", {"HERMES_UID": "4321"}, "runc")
    argv = _create_argv(calls)
    env = dict(
        argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-e"
    )
    assert env["HERMES_UID"] == "4321"


@pytest.mark.asyncio
async def test_write_config_uses_docker_cp_to_hermes_home(prov_capture):
    prov, calls = prov_capture
    await prov.write_config("cad-x", "model:\n  default: default\n")
    cp = next(c for c in calls if c and c[0] == "cp")
    assert cp[-1] == f"cad-x:{HERMES_CONFIG_PATH}"
    # source is a real temp file that we clean up
    assert not os.path.exists(cp[1])


@pytest.mark.asyncio
async def test_remove_drops_the_anon_volume(prov_capture):
    prov, calls = prov_capture
    await prov.remove("cad-x")
    rm = next(c for c in calls if c and c[0] == "rm")
    assert "-f" in rm and "-v" in rm
