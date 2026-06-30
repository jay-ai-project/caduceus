"""`caduceus` CLI (typer) — thin handlers over ControlAPIClient / GatewayService.

Output is human-readable by default, `--json` for scripts; errors → stderr +
non-zero exit (Q6). Business logic lives in the daemon services.
"""

from __future__ import annotations

import sys
from typing import Optional

import typer

from caduceus.cli import render
from caduceus.cli.client import ControlAPIClient, ControlError
from caduceus.cli.render import EXIT_RUNTIME, EXIT_USAGE
from caduceus.common.dto import ConfigChange, CreateSpec, RegisterSpec
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
def agent_create(name: str, model: Optional[str] = None,
                 upstream_url: Optional[str] = None, image: Optional[str] = None,
                 json_out: bool = typer.Option(False, "--json")):
    client = _client_or_exit()

    def go():
        view = client.create_agent(CreateSpec(name, model, upstream_url, image))
        render.render_agents([view], json_out) if json_out else render.emit(f"created agent '{view.name}' ({view.lifecycle})")
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
def agent_rm(name: str, force: bool = typer.Option(False, "--force")):
    client = _client_or_exit()

    def go():
        client.remove_agent(name, force=force)
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
def gateway_start(daemon: bool = typer.Option(False, "-d", "--daemon"),
                  foreground: bool = typer.Option(True, "--foreground/--no-foreground")):
    gw = get_gateway()
    try:
        gw.start(foreground=not daemon and foreground, daemonize=daemon)
    except Exception as exc:  # noqa: BLE001 — config/lock errors → clear message
        render.error(str(exc))
        raise typer.Exit(EXIT_RUNTIME)


@gateway_app.command("stop")
def gateway_stop():
    get_gateway().stop()
    render.emit("gateway stop signalled")


@gateway_app.command("status")
def gateway_status(json_out: bool = typer.Option(False, "--json")):
    render.render_status(get_gateway().status(), json_out)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
