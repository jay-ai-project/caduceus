# U2 Registry & Provisioner — Domain Entities

Technology-agnostic domain model for agent lifecycle + registry. (sbx/hermes command specifics are deferred to U2 Infrastructure Design / Code Generation.)

## Decisions (Functional Design Q1/Q2)
- **Q1=A**: caduceus name `<name>` → sandbox name **`cad-<name>`** (namespacing).
- **Q2=A**: remote agents get a minted token + AI-Gateway URL guidance; caduceus cannot auto-configure a remote hermes in v1 (remote config read-only).

---

## Enums

### AgentKind
`local` (sbx-provisioned) | `remote` (registered endpoint)

### Lifecycle
- local: `creating` → `running` ⇄ `stopped` ; `failed` (create error)
- remote: `registered`
- terminal: `removed` (record deleted)

### HealthLevel
`healthy` | `degraded` | `unhealthy` | `unknown`

---

## Entities

### AgentRecord  (persisted; the cross-unit contract — lives in `common/` models)
| Field | Type | Notes |
|---|---|---|
| name | str | user-facing, unique |
| kind | AgentKind | local/remote |
| sandbox_name | str? | `cad-<name>` (local only) |
| endpoint | str? | transport endpoint — local: published serve URL (`http://127.0.0.1:<port>`); remote: registered URL |
| serve_port | int? | published host port (local) |
| token | str | minted bearer token for AI-Gateway auth (both kinds) |
| serve_auth | str? | *(added in Infra Design)* credential for the agent's `hermes serve` endpoint (local; caduceus-generated). Used by U3 transport. |
| model_alias | str | `default` (v1; per-agent override is v2) |
| session_id | str? | hermes session id (set by U3 chat; nullable) |
| lifecycle | Lifecycle | see enum |
| last_health | HealthStatus? | cached |
| created_at / updated_at | iso str | |

### SandboxInfo  (from `sbx ls --json`)
| Field | Type |
|---|---|
| sandbox_name | str |
| container_status | running \| stopped \| missing |
| id | str? |

### AgentToken
| Field | Type | Notes |
|---|---|---|
| value | str | `secrets.token_urlsafe(32)`; unique |
| created_at | iso str | stored with file perm 600; never logged |

### ProvisionSpec  (input to create)
| Field | Type | Notes |
|---|---|---|
| name | str | |
| image | ImageRef | default from ImageBuilder |
| model_alias | str | `default` |
| extra_workspaces | list[str] | optional `:ro` mounts (passthrough to sbx) |

### RegisterSpec  (input to register)
| Field | Type | Notes |
|---|---|---|
| name | str | |
| endpoint | str | remote hermes URL |
| auth | str? | optional credential for the remote endpoint |

### HealthStatus
| Field | Type | Notes |
|---|---|---|
| level | HealthLevel | |
| shallow | bool | endpoint/sandbox reachable |
| deep | bool? | hermes responsive + caduceus upstream reachable (no LLM spend) |
| detail | str | |
| checked_at | iso str | |

### ImageRef
| Field | Type |
|---|---|
| tag | str (e.g. `caduceus/hermes:<ver>`) |
| exists | bool |

---

## Registry state document (`~/.caduceus/state.json`)
```
{ "version": 1, "agents": { "<name>": AgentRecord, ... } }
```
Atomic write (temp + os.replace); in-process lock serializes access (daemon).

## Relationships
- `ProvisionSpec` --create--> `AgentRecord(local)` (+ `SandboxInfo`, `AgentToken`)
- `RegisterSpec` --register--> `AgentRecord(remote)` (+ `AgentToken`)
- `AgentRecord` --health--> `HealthStatus`
- `AgentRecord.token` authenticates the agent at the U1 AI-Gateway (token→agent map = U1's `token_lookup`, backed by this registry).
