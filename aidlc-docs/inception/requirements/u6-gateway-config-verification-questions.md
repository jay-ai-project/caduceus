# U6 — `caduceus gateway config` · Requirements Verification Questions

**Request**: Add a `caduceus gateway config` command to view and change the gateway's
`upstream_base_url` and `default_model` settings.

Fill in each `[Answer]:` with a letter (A/B/C…). For **X) Other**, write your choice after the tag.
When done, reply that it's ready and I'll generate the requirements doc.

---

## Q1 — Apply semantics when the daemon is **running**
Today, settings are read once at `gateway start` (injected into `UpstreamClient` + routing).
Changing them therefore needs a decision on how they take effect on a live daemon.

- **A)** Hot-apply live (no restart): update the running gateway's upstream/model immediately **and** persist to `config.toml`. *(Recommended)*
- **B)** Persist to `config.toml` only; changes take effect on the next `gateway start` (print a "restart required" notice).
- **C)** Persist **and** automatically restart the daemon to apply.
- **X)** Other

[Answer]: A

---

## Q2 — Command interface
- **A)** `caduceus gateway config` with `--get` / `--json` to view, and dedicated `--upstream-url <url>` / `--model <model>` flags to set. *(Recommended — most discoverable)*
- **B)** Generic `--set key=value` (mirrors `agent config --set`).
- **C)** Both: dedicated flags **and** `--set key=value`.
- **X)** Other

[Answer]: A

---

## Q3 — Which keys are editable by this command
- **A)** Only `upstream_base_url` and `default_model`. *(Recommended — matches the request)*
- **B)** Those two **plus** `upstream_auth` (upstream API key/bearer).
- **C)** All bootstrap settings (also `control_bind`, `aigateway_bind`, `aigateway_advertise_host`, timeouts).
- **X)** Other

[Answer]: A

---

## Q4 — Behaviour when the daemon is **not running**
- **A)** Still works: edit `config.toml` directly when the daemon is down; when up, also apply per Q1. *(Recommended)*
- **B)** Require the daemon to be running (all changes go through the Control API).
- **X)** Other

[Answer]: A

---

## Q5 — Validation before applying
- **A)** Light only: non-empty + basic URL shape check; no network calls. *(Recommended — fast, predictable)*
- **B)** Probe upstream reachability (and/or that the model exists) before committing; warn but allow `--force` override.
- **C)** No validation.
- **X)** Other

[Answer]: A

---

## Q6 — Extensions for this cycle (inherited from the project)
Current project config: **Security = No**, **Resiliency = Yes (full)**, **Property-Based Testing = Yes (full)**.

- **A)** Keep inherited as-is. *(Recommended)*
- **B)** Change for this cycle (describe after the tag).

[Answer]: A
