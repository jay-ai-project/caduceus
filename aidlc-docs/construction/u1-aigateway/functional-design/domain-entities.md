# U1 AI-Gateway — Domain Entities

Technology-agnostic domain model for the AI-Gateway. (Transport/framework specifics are deferred to NFR/Infrastructure Design and Code Generation.)

## Design decisions (from Functional Design questions)
- **Q1=A**: agents are identified & authenticated by a **per-agent bearer token** (caduceus-issued, injected into the agent's hermes provider `api_key`).
- **Q2 (custom rule)**: request model `default` → rewritten to the configured **default model** (`your-model`); any other model string is **passed through unchanged**.
- **Q3=A**: **generic `/v1/*` pass-through** reverse proxy (chat/completions gets streaming handling; everything else is forwarded).

---

## Entities

### ProxyRequest
The normalized inbound request from an agent's hermes.
| Field | Type | Notes |
|---|---|---|
| method | enum(GET/POST/...) | HTTP method |
| path | string | e.g. `/v1/chat/completions`, `/v1/models`, `/v1/embeddings` |
| headers | map | includes `Authorization: Bearer <agent-token>` |
| body | bytes/json | OpenAI payload (may contain `model`, `stream`) |
| stream | bool | derived from body `stream:true` (chat/completions) |
| model | string? | from body, if present |
| agent_token | string? | parsed from Authorization |

### AgentIdentity
Result of authenticating `agent_token`.
| Field | Type | Notes |
|---|---|---|
| agent_id | string? | agent name; null if unknown |
| authenticated | bool | true if token maps to a known agent |

### UpstreamTarget
Where/how to forward (resolved per request).
| Field | Type | Notes |
|---|---|---|
| base_url | string | v1: always caduceus-configured upstream (`http://localhost:11434/v1`) |
| effective_model | string? | result of model-resolution rule |
| upstream_auth | string? | credentials for upstream (if any); NOT the agent token |
| connect_timeout_s | number | RESILIENCY-10 |
| idle_timeout_s | number | per-chunk read timeout for streams |

### Route
The decision binding an identity + request to an upstream target.
| Field | Type | Notes |
|---|---|---|
| agent | AgentIdentity | |
| target | UpstreamTarget | |
| rewrite_model | bool | true when request model == sentinel `default` |

### UpstreamResponse
| Field | Type | Notes |
|---|---|---|
| status | int | upstream HTTP status |
| streaming | bool | SSE vs unary |
| body / chunks | bytes / async stream | pass-through |

### ProxyError
Normalized error mapped to the OpenAI error JSON shape `{ "error": { type, message, code } }`.
| Field | Type | Notes |
|---|---|---|
| http_status | int | 401/404/4xx/502/504/5xx |
| type | string | `invalid_request_error`, `authentication_error`, `upstream_error`, `timeout_error` |
| message | string | human readable, **no secrets** |
| code | string? | optional machine code |

### ModelInfo / ModelList
For `/v1/models` responses (proxied upstream list **augmented** with the `default` alias).
| Field | Type | Notes |
|---|---|---|
| id | string | model id (`default`, `your-model`, ...) |
| object | "model" | |
| owned_by | string | `caduceus` for the alias |

---

## Relationships
- `ProxyRequest` --auth--> `AgentIdentity`
- (`AgentIdentity`, `ProxyRequest`) --resolve--> `Route` (contains `UpstreamTarget`)
- `Route` --forward--> `UpstreamResponse` | `ProxyError`
- `/v1/models` upstream `ModelList` --augment(`default`)--> response `ModelList`

## Constants
- **Sentinel model**: `default` (case-insensitive match).
- **Default model**: caduceus config `default_model` = `your-model`.
- **Upstream**: caduceus config `upstream_base_url` = `http://localhost:11434/v1`.
