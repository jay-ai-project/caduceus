# U2 Registry & Provisioner — Business Logic Model

Owns FR-A1..A6, FR-L2. Provides the **token→agent** map that U1's AI-Gateway authenticates against.

## create(spec) — local provisioning  [FR-A1]
```
validate_name(spec.name); ensure_unique(spec.name)
image  = ImageBuilder.ensure_image(spec.image)
token  = mint_token()
try:
    sandbox = Provisioner.create_sandbox("cad-"+name, image, env)      # sbx create shell -t image
    Provisioner.configure_hermes(sandbox,                              # provider -> AI-Gateway
        base_url = aigateway_advertise_url, api_key = token, model = "default")
    serve_port = Provisioner.start_serve(sandbox)                      # hermes serve + sbx ports publish
    record = AgentRecord(name, kind=local, sandbox_name, endpoint=loopback(serve_port),
                         token, model_alias="default", lifecycle=running)
    Registry.upsert(record)                                            # atomic persist
    health = HealthChecker.check(name, deep=False)                     # verify
    return record
except Exception:
    rollback: Provisioner.remove("cad-"+name) best-effort; discard token; do NOT persist
    raise clear error  (daemon stays up)
```

## register(spec) — remote  [FR-A2]
```
validate_name; ensure_unique
probe_reachable(spec.endpoint)            # basic connectivity (not a full handshake; U3 owns transport)
token = mint_token()
record = AgentRecord(name, kind=remote, endpoint, token, model_alias="default", lifecycle=registered)
Registry.upsert(record)
return record + GUIDANCE:                  # Q2=A
   "Point your remote hermes provider at:
      base_url = <AI-Gateway advertise URL reachable from the remote host>
      api_key  = <token>;  model = default"
```

## list(deep)  [FR-A3, FR-L2]
```
for rec in Registry.list():
    if rec.kind == local: reconcile lifecycle with sbx ls --json (running/stopped/missing)
    rec.last_health = HealthChecker.check(rec.name, deep) if requested else cached
return views (kind, lifecycle, health, endpoint)
```

## remove(name, force)  [FR-A4]
```
rec = Registry.get(name) or error
if rec.kind == local: Provisioner.stop+remove("cad-"+name) best-effort
discard token; Registry.delete(name)
```

## stop(name) / start(name)  [FR-A5]  (local only)
```
if rec.kind == remote: error "stop/start not supported for remote agents"
Provisioner.stop/start("cad-"+name); update lifecycle (idempotent)
```

## health(name, deep)  [FR-L2]
- **shallow**: local → sandbox running (sbx) AND serve endpoint accepts a connection; remote → endpoint reachable.
- **deep**: shallow AND hermes responds (transport health probe — U3) AND caduceus upstream reachable (`HealthChecker.check_upstream`). **No LLM completion is spent.**
- result cached on the record.

## Collaborators
- **Registry/StateStore** (persist), **Provisioner** (sbx subprocess), **ImageBuilder** (image), **HealthChecker** (status). Transport health probe is provided by U3 (injected) so U2 stays decoupled.

---

## Testable Properties (PBT-01)

| # | Property | Category |
|---|---|---|
| P-U2-1 | `AgentRecord` (and full state doc) JSON `save→load` round-trips to an equal value | Round-trip (PBT-02) |
| P-U2-2 | `validate_name` accepts valid names, rejects invalid; for local, `sandbox_name == "cad-"+name` | Invariant (PBT-03) |
| P-U2-3 | A local agent's configured provider always has `base_url == AI-Gateway URL` and `model == "default"` | Invariant (PBT-03) |
| P-U2-4 | `start∘start`, `stop∘stop` are idempotent (observable lifecycle); `remove∘remove` → not-found | Idempotence (PBT-04) |
| P-U2-5 | **Stateful registry**: random sequences of create/register/stop/start/remove keep invariants — names unique, removed absent, only valid transitions, persisted==in-memory (vs a reference model) | Stateful (PBT-06) |
| P-U2-6 | minted tokens are unique and meet an entropy/length floor | Invariant |

Example-based tests (PBT-10) pin: create happy path (mocked Provisioner), create rollback on failure, register guidance content, remove teardown, stop/start on remote → error.

## Notes
- Provisioner/ImageBuilder do real subprocess I/O → in unit tests they are **mocked**; real sbx/docker exercised in Build & Test integration tests (+ RESILIENCY-14 fault injection).
- The exact hermes provider-config mechanism (config.yaml `custom_providers` vs `hermes config set`) and `sbx` command lines are specified in U2 Infrastructure Design / Code Generation.
