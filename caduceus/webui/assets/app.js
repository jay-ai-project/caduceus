/* Caduceus Web UI — vanilla, no-build single module.
 * Consumes the Control API on the same origin: /status, /agents, /agents/{n}/...
 */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

const state = {
  agents: [],
  selected: null,   // agent name of the open chat
  streaming: false,
  es: null,         // the /api/events EventSource (push, no polling)
};

// ---------- tiny DOM helpers ----------
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("data-")) n.setAttribute(k, v);
    else if (k === "html") n.innerHTML = v;
    else n[k] = v;
  }
  for (const c of kids) if (c != null) n.append(c);
  return n;
}

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const b = await r.json(); msg = (b.error && b.error.message) || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

// ---------- SSE over fetch (POST-capable) ----------
async function* sseEvents(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        const t = line.trim();
        if (t.startsWith("data:")) {
          const payload = t.slice(5).trim();
          try { yield JSON.parse(payload); } catch (_) {}
        }
      }
    }
  }
}

// ================= Dashboard (push, not poll) =================
// One long-lived SSE connection to `/api/events` drives the whole dashboard:
// the server sends a snapshot on connect and a fresh snapshot on every state
// change (agent create/start/stop/remove/session, or a health sweep). No polling.
function connectEvents() {
  if (state.es) state.es.close();
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
    let msg; try { msg = JSON.parse(e.data); } catch (_) { return; }
    if (!msg || msg.type !== "snapshot") return;
    renderHeader(msg.status, true);
    state.agents = msg.agents || [];
    renderAgents();
  };
  // EventSource auto-reconnects; reflect the outage in the header until it does.
  es.onerror = () => renderHeader(null, false);
  state.es = es;
}

function renderHeader(status, up) {
  const elS = $("#gw-status");
  if (!up || !status) { elS.textContent = "daemon unreachable"; elS.className = "gw-status down"; return; }
  elS.className = "gw-status up";
  elS.textContent = `running · ${status.agent_count} agents · upstream ${status.upstream} · v${status.version}`;
}

function badge(cls, value) {
  return el("span", { class: `badge b-${value}`, text: value });
}

function renderAgents() {
  const list = $("#agent-list");
  list.innerHTML = "";
  if (!state.agents.length) {
    list.append(el("div", { class: "muted", text: "No agents yet. Click + Add." }));
    return;
  }
  for (const a of state.agents) {
    const remote = a.kind === "remote";
    const card = el("div", {
      class: "agent-card" + (a.name === state.selected ? " selected" : ""),
      "data-testid": `agent-card-${a.name}`,
    });
    card.append(
      el("div", { class: "row1" },
        el("span", { class: "name", text: a.name }),
        el("span", { class: "badge kind", text: a.kind }),
      ),
      el("div", { class: "row1", style: "margin-top:6px;gap:6px;justify-content:flex-start" },
        badge("lc", a.lifecycle), badge("h", a.health),
      ),
      el("div", { class: "meta", text: `${a.endpoint || "—"} · model ${a.model_alias}${a.has_session ? " · session" : ""}` }),
    );

    const actions = el("div", { class: "actions" });
    actions.append(el("button", { class: "btn sm primary", text: "Chat",
      "data-testid": `chat-${a.name}`, onclick: (e) => { e.stopPropagation(); openChat(a.name); } }));
    if (a.lifecycle === "running") {
      actions.append(el("button", { class: "btn sm", text: "Stop", disabled: remote,
        title: remote ? "remote agents can't be stopped here" : "",
        onclick: (e) => { e.stopPropagation(); agentAction(a.name, "stop"); } }));
    } else {
      actions.append(el("button", { class: "btn sm", text: "Start", disabled: remote,
        onclick: (e) => { e.stopPropagation(); agentAction(a.name, "start"); } }));
    }
    actions.append(el("button", { class: "btn sm danger", text: "Remove",
      "data-testid": `remove-${a.name}`,
      onclick: (e) => { e.stopPropagation(); removeAgent(a.name); } }));
    card.append(actions);
    card.onclick = () => openChat(a.name);
    list.append(card);
  }
}

async function agentAction(name, action) {
  // No manual refresh: the mutation broadcasts a fresh snapshot over /api/events.
  try { await fetchJSON(`/agents/${encodeURIComponent(name)}/${action}`, { method: "POST" }); }
  catch (e) { alert(`${action} failed: ${e.message}`); }
}

async function removeAgent(name) {
  if (!confirm(`Remove agent '${name}'? This is irreversible.`)) return;
  try { await fetchJSON(`/agents/${encodeURIComponent(name)}?force=true`, { method: "DELETE" }); }
  catch (e) { alert(`remove failed: ${e.message}`); }
  if (state.selected === name) { state.selected = null; showEmpty(); }
}

// ================= Add agent modal =================
function openModal() { $("#modal-backdrop").classList.remove("hidden"); resetModal(); }
function closeModal() { $("#modal-backdrop").classList.add("hidden"); }
function resetModal() {
  $("#modal-log").classList.add("hidden");
  $("#modal-log").textContent = "";
  switchTab("local");
}
function switchTab(tab) {
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t.dataset.tab === tab);
  $("#form-local").classList.toggle("hidden", tab !== "local");
  $("#form-remote").classList.toggle("hidden", tab !== "remote");
}

function logLine(s) {
  const log = $("#modal-log");
  log.classList.remove("hidden");
  log.textContent += s + "\n";
  log.scrollTop = log.scrollHeight;
}

async function submitLocal(ev) {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const name = (f.get("name") || "").trim();
  if (!name) return;
  const body = {
    name,
    model: (f.get("model") || "").trim() || null,
    upstream_url: (f.get("upstream_url") || "").trim() || null,
    image: (f.get("image") || "").trim() || null,
  };
  logLine(`creating '${name}'…`);
  try {
    const resp = await fetch("/agents", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    for await (const ev2 of sseEvents(resp)) {
      if (ev2.event === "progress") logLine(`  → ${ev2.phase}${ev2.detail ? " (" + ev2.detail + ")" : ""}`);
      else if (ev2.event === "done") { logLine(`✓ created '${ev2.agent.name}' (${ev2.agent.lifecycle})`); setTimeout(closeModal, 700); }
      else if (ev2.event === "accepted") { logLine(`✓ accepted '${ev2.agent.name}' (${ev2.agent.lifecycle}) — provisioning…`); setTimeout(closeModal, 700); }
      else if (ev2.event === "error") logLine(`✗ error: ${ev2.message}`);
    }
  } catch (e) { logLine(`✗ ${e.message}`); }
}

async function submitRemote(ev) {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const name = (f.get("name") || "").trim();
  const endpoint = (f.get("endpoint") || "").trim();
  if (!name || !/^https?:\/\//.test(endpoint)) { logLine("✗ name + http(s) endpoint required"); return; }
  const body = { name, endpoint, auth: (f.get("auth") || "").trim() || null };
  try {
    const res = await fetchJSON("/agents/register", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    logLine(`✓ registered '${name}'`);
    if (res.guidance) logLine(res.guidance);
    // dashboard refresh arrives via the /api/events snapshot broadcast.
  } catch (e) { logLine(`✗ ${e.message}`); }
}

// ================= Chat =================
function showEmpty() { $("#chat").classList.add("hidden"); $("#chat-empty").classList.remove("hidden"); }
function showChat() { $("#chat-empty").classList.add("hidden"); $("#chat").classList.remove("hidden"); }

async function openChat(name) {
  state.selected = name;
  renderAgents();
  showChat();
  $("#chat-head").innerHTML = "";
  $("#chat-head").append(el("span", { text: name }), el("span", { class: "muted", text: "ephemeral session" }));
  const tr = $("#transcript");
  tr.innerHTML = "";
  tr.append(el("div", { class: "muted", text: "loading history…" }));
  try {
    const hist = await fetchJSON(`/agents/${encodeURIComponent(name)}/history`);
    tr.innerHTML = "";
    for (const t of (hist.turns || [])) addBubble(t.role, t.text);
    if (!(hist.turns || []).length) tr.append(el("div", { class: "muted", text: "No prior history." }));
  } catch (_) { tr.innerHTML = ""; }
  $("#composer-input").focus();
}

function addBubble(role, text) {
  const b = el("div", { class: `bubble ${role}` });
  b.append(el("span", { class: "answer", text: text || "" }));
  $("#transcript").append(b);
  scrollTranscript();
  return b;
}

function scrollTranscript() { const tr = $("#transcript"); tr.scrollTop = tr.scrollHeight; }

function ensureThinking(bubble) {
  let d = bubble._thinking;
  if (!d) {
    d = el("details", { class: "aux thinking" }, el("summary", { text: "💭 thinking" }),
      el("div", { class: "think-text" }));
    bubble.insertBefore(d, bubble._answer);
    bubble._thinking = d;
  }
  return d;
}

function upsertTool(bubble, meta) {
  bubble._tools = bubble._tools || {};
  let card = bubble._tools[meta.id];
  if (!card) {
    card = el("details", { class: "aux tool-card", open: false });
    card._summary = el("summary", {});
    card._io = el("div", {});
    card.append(card._summary, card._io);
    bubble.insertBefore(card, bubble._answer);
    bubble._tools[meta.id] = card;
  }
  card._summary.innerHTML = "";
  card._summary.append(
    el("span", { class: "tool-name", text: `🔧 ${meta.name || "tool"}` }),
    el("span", { class: `badge b-${meta.status === "completed" ? "running" : meta.status === "failed" ? "failed" : "creating"}`,
      text: meta.status, style: "margin-left:8px" }),
  );
  card._io.innerHTML = "";
  if (meta.input) card._io.append(el("div", { class: "tool-io" }, el("span", { class: "label", text: "input: " }), document.createTextNode(meta.input)));
  if (meta.output) card._io.append(el("div", { class: "tool-io" }, el("span", { class: "label", text: "output: " }), document.createTextNode(meta.output)));
  scrollTranscript();
}

async function sendMessage(text) {
  const name = state.selected;
  if (!name || !text.trim() || state.streaming) return;
  state.streaming = true;
  setComposerEnabled(false);

  addBubble("user", text);
  const bubble = el("div", { class: "bubble assistant" });
  bubble._answer = el("span", { class: "answer" });
  bubble.append(bubble._answer);
  $("#transcript").append(bubble);
  scrollTranscript();

  try {
    const resp = await fetch(`/agents/${encodeURIComponent(name)}/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    for await (const ev of sseEvents(resp)) {
      dispatchChatEvent(bubble, ev);
    }
  } catch (e) {
    bubble.classList.add("error");
    bubble._answer.textContent += `\n[stream error: ${e.message}]`;
  } finally {
    if (bubble._thinking) bubble._thinking.open = false;
    state.streaming = false;
    setComposerEnabled(true);
    $("#composer-input").focus();
  }
}

function dispatchChatEvent(bubble, ev) {
  switch (ev.type) {
    case "token":
    case "message":
      bubble._answer.textContent += ev.data || "";
      break;
    case "thinking": {
      const d = ensureThinking(bubble);
      d.querySelector(".think-text").textContent += ev.data || "";
      break;
    }
    case "tool_call":
      if (ev.meta) upsertTool(bubble, ev.meta);
      break;
    case "error":
      bubble.classList.add("error");
      bubble._answer.textContent += (bubble._answer.textContent ? "\n" : "") + `[error] ${ev.data || ""}`;
      break;
    case "done":
      break;
  }
  scrollTranscript();
}

function setComposerEnabled(on) {
  $("#composer-input").disabled = !on;
  $("#composer-send").disabled = !on;
}

// ================= wiring =================
function init() {
  $("#add-agent-btn").onclick = openModal;
  $("#modal-close").onclick = closeModal;
  $("#modal-backdrop").onclick = (e) => { if (e.target.id === "modal-backdrop") closeModal(); };
  for (const t of document.querySelectorAll(".tab")) t.onclick = () => switchTab(t.dataset.tab);
  $("#form-local").onsubmit = submitLocal;
  $("#form-remote").onsubmit = submitRemote;

  const input = $("#composer-input");
  $("#composer").onsubmit = (e) => { e.preventDefault(); const v = input.value; input.value = ""; sendMessage(v); };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; });

  connectEvents();             // open the /api/events push stream (snapshot on connect)
}

// run now if the DOM is already parsed (script is at end of <body>), else wait
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
