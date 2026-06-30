"""Unit tests for AcpTransport — drives a fake `hermes acp` process (no Docker).

A `FakeAcpProcess` emulates the agent side of the ACP stdio JSON-RPC: it parses
each request written to stdin and feeds scripted responses/notifications to
stdout, so the transport's protocol mapping, agent→client request handling,
session resume, and cooperative cancel are all exercised in-process.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from caduceus.common.models import AgentKind, AgentRecord, HealthLevel
from caduceus.transport.acp import AcpTransport
from caduceus.transport.events import ChatEventType


class _FakeStdin:
    def __init__(self, proc: "FakeAcpProcess"):
        self._proc = proc

    def write(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                self._proc.on_request(json.loads(line))

    async def drain(self) -> None:
        return None


class FakeAcpProcess:
    """Scripted ACP agent. `prompt_updates` are emitted as session/update
    notifications before the final session/prompt response."""

    def __init__(self, *, session_id="sess-1", load_ok=False, prompt_updates=None,
                 prompt_error=None, extra_requests=None, raw_updates=None, load_replay=None):
        self.stdout = asyncio.StreamReader()
        self.stdin = _FakeStdin(self)
        self.returncode = None
        self.session_id = session_id
        self.load_ok = load_ok
        self.prompt_updates = prompt_updates if prompt_updates is not None else [("PO",), ("NG",)]
        self.prompt_error = prompt_error
        self.extra_requests = extra_requests or []   # agent→client requests during prompt
        self.raw_updates = raw_updates               # full `update` dicts emitted during prompt
        self.load_replay = load_replay or []         # `update` dicts replayed during session/load
        self.received: list[dict] = []
        self.client_replies: list[dict] = []

    def _feed_update(self, update: dict) -> None:
        self._feed({"jsonrpc": "2.0", "method": "session/update",
                    "params": {"sessionId": self.session_id, "update": update}})

    def _feed(self, obj: dict) -> None:
        self.stdout.feed_data((json.dumps(obj) + "\n").encode("utf-8"))

    def on_request(self, msg: dict) -> None:
        self.received.append(msg)
        method = msg.get("method")
        rid = msg.get("id")
        if rid is None:
            # a client notification (e.g. session/cancel) or a client→agent reply
            if "result" in msg:
                self.client_replies.append(msg)
            return
        if "result" in msg:  # reply to an agent→client request
            self.client_replies.append(msg)
            return
        if method == "initialize":
            self._feed({"jsonrpc": "2.0", "id": rid, "result": {"agentCapabilities": {}}})
        elif method == "session/new":
            self._feed({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": self.session_id}})
        elif method == "session/load":
            if self.load_ok:
                for upd in self.load_replay:
                    self._feed_update(upd)  # replay prior turns before the result
                self._feed({"jsonrpc": "2.0", "id": rid, "result": {}})
            else:
                self._feed({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "unknown session"}})
        elif method == "session/prompt":
            for req in self.extra_requests:
                self._feed(req)  # agent→client request mid-stream
            if self.raw_updates is not None:
                for upd in self.raw_updates:
                    self._feed_update(upd)
            else:
                for upd in self.prompt_updates:
                    self._feed_update({"sessionUpdate": "agent_message_chunk",
                                       "content": {"type": "text", "text": upd[0]}})
            if self.prompt_error is not None:
                self._feed({"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": self.prompt_error}})
            else:
                self._feed({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})

    def terminate(self) -> None:
        self.stdout.feed_eof()

    def kill(self) -> None:
        self.stdout.feed_eof()

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def _local_rec(**kw) -> AgentRecord:
    return AgentRecord(name="a1", kind=AgentKind.local, token="tok", sandbox_name="cad-a1", **kw)


def _transport(proc: FakeAcpProcess, rec=None) -> AcpTransport:
    async def spawn():
        return proc
    return AcpTransport(rec or _local_rec(), spawn=spawn)


async def _collect(t, message="hi"):
    return [ev async for ev in t.chat_stream(t.rec.session_id, message)]


async def test_open_initializes_and_creates_session():
    proc = FakeAcpProcess(session_id="sess-X")
    t = _transport(proc)
    await t.open()
    assert t.session_id == "sess-X"
    methods = [m["method"] for m in proc.received if "method" in m and "id" in m and "result" not in m]
    assert methods[:2] == ["initialize", "session/new"]
    await t.close()


async def test_session_cwd_is_workspace_path():
    proc = FakeAcpProcess()
    t = _transport(proc, rec=_local_rec(workspace_path="/ws/cad-a1"))
    await t.open()
    new_req = next(m for m in proc.received if m.get("method") == "session/new")
    assert new_req["params"]["cwd"] == "/ws/cad-a1"
    await t.close()


async def test_session_cwd_falls_back_to_root():
    proc = FakeAcpProcess()
    t = _transport(proc, rec=_local_rec())  # no workspace_path
    await t.open()
    new_req = next(m for m in proc.received if m.get("method") == "session/new")
    assert new_req["params"]["cwd"] == "/root"
    await t.close()


async def test_prompt_streams_tokens_then_done():
    t = _transport(FakeAcpProcess(prompt_updates=[("Hello ",), ("world",)]))
    evs = await _collect(t)
    assert [e.type for e in evs] == [ChatEventType.token, ChatEventType.token, ChatEventType.done]
    assert "".join(e.data for e in evs if e.type == ChatEventType.token) == "Hello world"


async def test_prompt_error_maps_to_terminal_error():
    t = _transport(FakeAcpProcess(prompt_error="boom"))
    evs = await _collect(t)
    assert evs[-1].type == ChatEventType.error
    assert "boom" in evs[-1].data


async def test_resume_existing_session_via_load():
    proc = FakeAcpProcess(session_id="ignored", load_ok=True)
    t = _transport(proc, rec=_local_rec(session_id="prev-sess"))
    await t.open()
    assert t.session_id == "prev-sess"  # loaded, not recreated
    assert any(m.get("method") == "session/load" for m in proc.received)
    await t.close()


async def test_stale_session_load_fails_then_recreates():
    proc = FakeAcpProcess(session_id="fresh", load_ok=False)
    t = _transport(proc, rec=_local_rec(session_id="stale"))
    await t.open()
    assert t.session_id == "fresh"  # transparent recreate (Q1)
    await t.close()


async def test_agent_request_permission_is_auto_approved():
    perm_req = {"jsonrpc": "2.0", "id": 99, "method": "session/request_permission",
                "params": {"sessionId": "sess-1",
                           "options": [{"optionId": "deny", "kind": "reject_once"},
                                       {"optionId": "allow_once", "kind": "allow_once"}]}}
    proc = FakeAcpProcess(extra_requests=[perm_req], prompt_updates=[("ok",)])
    t = _transport(proc)
    evs = await _collect(t)
    assert evs[-1].type == ChatEventType.done
    reply = next(r for r in proc.client_replies if r.get("id") == 99)
    assert reply["result"]["outcome"]["optionId"] == "allow_once"


async def test_cooperative_cancel_emits_done_cancelled():
    t = _transport(FakeAcpProcess())
    await t.open()
    t.request_cancel()
    evs = [ev async for ev in t.chat_stream(t.rec.session_id, "hi")]
    assert evs == [evs[0]]
    assert evs[0].type == ChatEventType.done and evs[0].code == "cancelled"
    await t.close()


async def test_health_ok_when_handshake_succeeds():
    t = _transport(FakeAcpProcess())
    hs = await t.health()
    assert hs.level == HealthLevel.healthy and hs.shallow
    await t.close()


async def test_health_unhealthy_when_spawn_fails():
    async def bad_spawn():
        raise RuntimeError("sbx exec failed")
    t = AcpTransport(_local_rec(), spawn=bad_spawn)
    hs = await t.health()
    assert hs.level == HealthLevel.unhealthy and not hs.shallow


# ---- U5: thinking + tool-call mapping ----------------------------
async def test_thought_chunk_maps_to_thinking():
    updates = [
        {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "let me think"}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "answer"}},
    ]
    t = _transport(FakeAcpProcess(raw_updates=updates))
    evs = await _collect(t)
    assert [e.type for e in evs] == [ChatEventType.thinking, ChatEventType.token, ChatEventType.done]
    assert evs[0].data == "let me think"


async def test_tool_call_and_update_map_to_tool_events():
    updates = [
        {"sessionUpdate": "tool_call", "toolCallId": "tc1", "kind": "read", "title": "read_file",
         "status": "in_progress", "rawInput": {"path": "/x"}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "tc1", "status": "completed",
         "content": [{"type": "content", "content": {"type": "text", "text": "file body"}}]},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "done"}},
    ]
    t = _transport(FakeAcpProcess(raw_updates=updates))
    evs = await _collect(t)
    tools = [e for e in evs if e.type == ChatEventType.tool_call]
    assert len(tools) == 2
    assert tools[0].meta["id"] == "tc1" and tools[0].meta["status"] == "in_progress"
    assert '"path": "/x"' in tools[0].meta["input"]
    assert tools[1].meta["status"] == "completed" and "file body" in tools[1].meta["output"]


async def test_malformed_update_is_ignored_not_fatal():
    updates = [
        {"sessionUpdate": "tool_call"},  # no toolCallId → ignored
        {"sessionUpdate": "weird_kind", "content": {"text": "x"}},  # unknown → ignored
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}},
    ]
    t = _transport(FakeAcpProcess(raw_updates=updates))
    evs = await _collect(t)
    assert [e.type for e in evs] == [ChatEventType.token, ChatEventType.done]


# ---- U5: history replay via session/load -------------------------
async def test_load_history_returns_coalesced_turns():
    replay = [
        {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "hello"}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hi "}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "there"}},
        {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "bye"}},
    ]
    proc = FakeAcpProcess(load_ok=True, load_replay=replay)
    t = _transport(proc, rec=_local_rec(session_id="sess-9"))
    turns = await t.load_history("sess-9")
    assert [(x.role, x.text) for x in turns] == [
        ("user", "hello"), ("assistant", "hi there"), ("user", "bye")]


async def test_load_history_empty_on_load_failure():
    proc = FakeAcpProcess(load_ok=False)
    t = _transport(proc, rec=_local_rec(session_id="stale"))
    assert await t.load_history("stale") == []


async def test_load_history_empty_without_session():
    t = _transport(FakeAcpProcess())
    assert await t.load_history(None) == []
