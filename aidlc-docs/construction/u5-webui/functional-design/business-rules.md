# U5 Web UI — Business Rules

## Serving & exposure
- **BR-W1** — The Web UI is served **only** on the Control API loopback listener (`127.0.0.1:9700`). It MUST NOT be reachable on the AI-Gateway listener (`0.0.0.0:9701`).
- **BR-W2** — Static assets ship inside the package (`caduceus/webui/assets/`) and are included in the wheel; a wheel-installed `caduceus` serves the UI with no extra files or build step.
- **BR-W3** — No authentication (loopback personal tool). No secrets (`token`, `serve_auth`, `api_key`) are ever sent to the browser; the UI consumes only secret-free projections (`AgentView`, `GatewayStatus`).
- **BR-W4** — UI lives under `/ui`; `GET /` redirects to `/ui/`. UI mounting MUST NOT shadow existing API routes (`/status`, `/agents…`, `/healthz`).

## Event model (additive, compatibility)
- **BR-W5** — The chat event extension is **additive**: existing event types and the terminal-event invariant (exactly one `error`/`done`, nothing after) are unchanged. `thinking` and `tool_call` are non-terminal.
- **BR-W6** — A malformed/partial ACP `session/update` MUST NOT break the chat stream: missing fields default to empty; the update is best-effort mapped or ignored, never raised.
- **BR-W7** — `tool_call` `input`/`output` are truncated to a cap (default **4 KiB** each) with an ellipsis marker, to bound SSE frame size.
- **BR-W8** — CLI backward-compatibility: the CLI chat renderer continues to work; unknown-to-CLI event types (`thinking`/`tool_call`) are silently ignored there (console output stays clean). `ChatEvent.from_dict` MUST accept the new types.

## History (best-effort)
- **BR-W9** — History load is **best-effort and local-only**: remote agents, sessionless agents, or any load failure yield an empty transcript with no error surfaced to the UI. History is text-only (user/assistant turns; past thinking/tool not reconstructed).
- **BR-W10** — History capture uses a **dedicated short-lived** transport so it never disturbs the pooled live-chat transport / running session.

## Agent actions (inherited constraints)
- **BR-W11** — Remote agents: `start`/`stop` are not offered/enabled in the UI (inherits U2 **BR-A10**: remote lifecycle control not possible). The UI reflects this (disabled controls).
- **BR-W12** — Destructive actions (remove) require an explicit in-UI confirmation step.

## Liveness & errors
- **BR-W13** — Dashboard refreshes by polling (default 3 s). A failed poll (daemon down) shows a clear "daemon not running / unreachable" state rather than stale-without-notice data.
- **BR-W14** — All long/streaming operations (provision, chat) surface terminal success/error explicitly; the UI never leaves a spinner without resolution (timeouts → error state).
