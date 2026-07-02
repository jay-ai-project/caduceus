"""`caduceus` CLI (typer) — thin handlers over ControlAPIClient / GatewayService.

Output is human-readable by default, `--json` for scripts; errors → stderr +
non-zero exit (Q6). Business logic lives in the daemon services.
"""

from __future__ import annotations

from typing import Optional

import typer

from caduceus.cli import render
from caduceus.cli.client import ControlAPIClient, ControlError
from caduceus.cli.render import EXIT_RUNTIME, EXIT_USAGE
from caduceus.common.dto import AgentView, ConfigChange, CreateSpec, RegisterSpec
from caduceus.transport.events import ChatEventType

app = typer.Typer(help="caduceus — gateway hub + CLI for sandboxed hermes agents", no_args_is_help=True)
agent_app = typer.Typer(help="Manage agents", no_args_is_help=True)
gateway_app = typer.Typer(help="Manage the caduceus daemon", no_args_is_help=True)
app.add_typer(agent_app, name="agent")
app.add_typer(gateway_app, name="gateway")


# ---- factories (patched in tests) --------------------------------
def get_client() -> ControlAPIClient:
    return ControlAPIClient()


def get_gateway():
    from caduceus.daemon.gateway import GatewayService

    return GatewayService()


def _client_or_exit() -> ControlAPIClient:
    client = get_client()
    if not client.is_daemon_up():
        render.error("caduceus daemon is not running. Start it with `caduceus gateway start`.")
        raise typer.Exit(EXIT_RUNTIME)
    return client


def _run(fn):
    try:
        fn()
    except ControlError as exc:
        render.error(str(exc))
        raise typer.Exit(exc.exit_code)


# ================= agent commands =================
@agent_app.command("create")
def agent_create(name: str,
                 model: Optional[str] = typer.Option(
                     None, "--model", help="model alias for this agent (default: gateway default)"),
                 image: Optional[str] = typer.Option(
                     None, "--image", help="agent image tag override (default: pinned hermes image)"),
                 wait: bool = typer.Option(False, "--wait/--no-wait",
                                           help="block until the agent is provisioned & ready"),
                 json_out: bool = typer.Option(False, "--json")):
    client = _client_or_exit()

    def go():
        view = None  # terminal record (wait: done; background: accepted)
        for ev in client.create_agent(CreateSpec(name, model=model, image=image), wait=wait):
            kind = ev.get("event")
            if kind == "progress":
                render.progress(ev.get("phase", ""), ev.get("detail", ""))
            elif kind in ("done", "accepted"):
                view = AgentView.from_dict(ev["agent"])
        if view is None:
            render.error("create did not start" if not wait else "create did not complete")
            raise typer.Exit(EXIT_RUNTIME)
        if json_out:
            render.render_agents([view], json_out)
        elif wait:
            render.emit(f"created agent '{view.name}' ({view.lifecycle})")
        else:
            render.emit(f"creating agent '{view.name}' in the background "
                        f"— check `caduceus agent ls`")
    _run(go)


@agent_app.command("register")
def agent_register(name: str, endpoint: str = typer.Option(..., "--endpoint"),
                   auth: Optional[str] = typer.Option(None, "--auth"),
                   json_out: bool = typer.Option(False, "--json")):
    client = _client_or_exit()

    def go():
        res = client.register_agent(RegisterSpec(name, endpoint, auth))
        if json_out:
            render.emit_json(res)
        else:
            render.emit(f"registered remote agent '{name}'")
            if res.get("guidance"):
                render.emit(res["guidance"])
    _run(go)


@agent_app.command("ls")
def agent_ls(json_out: bool = typer.Option(False, "--json"),
             deep: bool = typer.Option(False, "--deep")):
    client = _client_or_exit()
    _run(lambda: render.render_agents(client.list_agents(deep=deep), json_out))


@agent_app.command("rm")
def agent_rm(name: str):
    client = _client_or_exit()

    def go():
        client.remove_agent(name)
        render.emit(f"removed agent '{name}'")
    _run(go)


@agent_app.command("stop")
def agent_stop(name: str):
    client = _client_or_exit()
    _run(lambda: render.emit(f"stopped '{client.stop_agent(name).name}'"))


@agent_app.command("start")
def agent_start(name: str):
    client = _client_or_exit()
    _run(lambda: render.emit(f"started '{client.start_agent(name).name}'"))


@agent_app.command("logs")
def agent_logs(name: str, follow: bool = typer.Option(False, "-f", "--follow")):
    client = _client_or_exit()

    def go():
        for line in client.logs(name, follow=follow):
            render.emit(line)
    _run(go)


@agent_app.command("config")
def agent_config(
    name: str,
    get: bool = typer.Option(False, "--get"),
    json_out: bool = typer.Option(False, "--json"),
    add_skill: list[str] = typer.Option(None, "--add-skill"),
    remove_skill: list[str] = typer.Option(None, "--remove-skill"),
    enable_tool: list[str] = typer.Option(None, "--enable-tool"),
    disable_tool: list[str] = typer.Option(None, "--disable-tool"),
    soul: Optional[str] = typer.Option(None, "--soul"),
    soul_file: Optional[str] = typer.Option(None, "--soul-file"),
    set_: list[str] = typer.Option(None, "--set", help="key=value"),
):
    client = _client_or_exit()

    if get:
        _run(lambda: render.render_config(client.get_config(name), json_out))
        return

    if soul is not None and soul_file is not None:
        render.error("provide either --soul or --soul-file, not both")
        raise typer.Exit(EXIT_USAGE)

    core = {}
    for kv in (set_ or []):
        if "=" not in kv:
            render.error(f"--set expects key=value, got '{kv}'")
            raise typer.Exit(EXIT_USAGE)
        k, _, v = kv.partition("=")
        core[k] = v

    change = ConfigChange(
        add_skills=list(add_skill or []), remove_skills=list(remove_skill or []),
        enable_tools=list(enable_tool or []), disable_tools=list(disable_tool or []),
        soul=soul, soul_file=soul_file, set_core=core,
    )
    if change.is_empty():
        render.error("no changes requested (use --get to view, or pass edit options)")
        raise typer.Exit(EXIT_USAGE)
    _run(lambda: render.render_config_result(client.set_config(name, change), json_out))


@agent_app.command("chat")
def agent_chat(name: str, query: Optional[str] = typer.Argument(None)):
    client = _client_or_exit()
    if query is not None:
        raise typer.Exit(_chat_once(client, name, query))
    # interactive REPL
    render.emit(f"chat with '{name}' — Ctrl-D to exit")
    while True:
        try:
            line = input("> ")
        except EOFError:
            render.emit("")
            break
        if not line.strip():
            continue
        code = _chat_once(client, name, line)
        if code != 0:
            raise typer.Exit(code)


def _chat_once(client: ControlAPIClient, name: str, message: str) -> int:
    try:
        for ev in client.chat(name, message):
            if ev.type == ChatEventType.token:
                print(ev.data, end="", flush=True)
            elif ev.type == ChatEventType.message:
                print(ev.data, end="", flush=True)
            elif ev.type == ChatEventType.error:
                print()
                render.error(f"chat error: {ev.data}")
                return EXIT_RUNTIME
            elif ev.type == ChatEventType.done:
                print()
        return 0
    except ControlError as exc:
        render.error(str(exc))
        return exc.exit_code


# ================= gateway commands =================
@gateway_app.command("start")
def gateway_start(daemon: bool = typer.Option(False, "-d", "--daemon")):
    gw = get_gateway()
    try:
        gw.start(daemonize=daemon)
    except Exception as exc:  # noqa: BLE001 — config/lock errors → clear message
        render.error(str(exc))
        raise typer.Exit(EXIT_RUNTIME)


@gateway_app.command("stop")
def gateway_stop():
    get_gateway().stop()
    render.emit("gateway stop signalled")


@gateway_app.command("status")
def gateway_status(json_out: bool = typer.Option(False, "--json")):
    # Prefer the running daemon's own /status (live upstream health + uptime);
    # fall back to the local pid-file view when it is down/unreachable.
    client = get_client()
    if client.is_daemon_up():
        _run(lambda: render.render_status(client.status(), json_out))
    else:
        render.render_status(get_gateway().status(), json_out)


#: Same location the daemon reads/writes (GatewayService default state dir).
def _config_path():
    from pathlib import Path

    return Path("~/.caduceus/config.toml").expanduser()


@gateway_app.command("config")
def gateway_config(
    get: bool = typer.Option(False, "--get", help="show current settings (default when no --set flags)"),
    json_out: bool = typer.Option(False, "--json"),
    upstream_url: Optional[str] = typer.Option(None, "--upstream-url", help="set upstream LLM base URL"),
    model: Optional[str] = typer.Option(None, "--model", help="set default model"),
    runtime: Optional[str] = typer.Option(None, "--runtime", help="container runtime: runc | runsc"),
):
    """View or change the gateway's `upstream_base_url` / `default_model` / `container_runtime`.

    Applies live when the daemon is running (no restart); otherwise edits
    `~/.caduceus/config.toml` directly (effective on next `gateway start`).
    `--runtime` applies to newly-spawned agent containers.
    """
    from caduceus.common.dto import GatewayConfigChange
    from caduceus.common.settings import Settings
    from caduceus.config import gateway_config as gwc

    client = get_client()
    up = client.is_daemon_up()
    is_set = upstream_url is not None or model is not None or runtime is not None

    # ---- view (no set flags, or explicit --get) ----
    if not is_set:
        if up:
            _run(lambda: render.render_gateway_config(client.get_gateway_config(), json_out))
        else:
            settings = Settings.from_env_and_file(_config_path())
            render.render_gateway_config(gwc.view_from_settings(settings, source="file"), json_out)
        return

    # ---- set ----
    change = GatewayConfigChange(upstream_base_url=upstream_url, default_model=model,
                                 container_runtime=runtime)
    try:
        gwc.validate_change(change)
    except ValueError as exc:
        render.error(str(exc))
        raise typer.Exit(EXIT_USAGE)

    if up:
        _run(lambda: render.render_gateway_config_applied(
            client.set_gateway_config(change), change, live=True, as_json=json_out))
    else:
        path = _config_path()
        gwc.apply_to_toml(path, change)
        settings = Settings.from_env_and_file(path)
        render.render_gateway_config_applied(
            gwc.view_from_settings(settings, source="file"), change, live=False, as_json=json_out)


# ================= doctor =================
@app.command("doctor")
def doctor(json_out: bool = typer.Option(False, "--json")):
    """Check environment readiness: Docker, hermes image, container runtime (gVisor),
    and daemon reachability. Prints gVisor install guidance when runsc is desired but
    missing; never installs anything. Exit code is non-zero if a required check fails.
    """
    from caduceus.common.settings import Settings
    from caduceus.config import doctor as doc

    settings = Settings.from_env_and_file(_config_path())
    daemon_up = get_client().is_daemon_up()
    report = doc.run_doctor(container_runtime=settings.container_runtime, daemon_up=daemon_up)
    render.render_doctor(report, json_out)
    if not report.ok:
        raise typer.Exit(EXIT_RUNTIME)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
