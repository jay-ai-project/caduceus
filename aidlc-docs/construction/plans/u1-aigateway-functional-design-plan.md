# U1 AI-Gateway — Functional Design Plan

**Unit**: U1 — AI-Gateway (OpenAI-compatible LLM proxy)
**Owns**: FR-P1..P6
**Scope (technology-agnostic business logic)**: proxy request handling, agent identification, model/route resolution, streaming semantics, error mapping, default-vs-override routing.

Fill `[Answer]:` in Part B, then say "완료".

---

## Part A — Artifacts to generate (after answers)
- [x] `construction/u1-aigateway/functional-design/domain-entities.md` — entities (ProxyRequest, Route, AgentIdentity, UpstreamTarget, ModelInfo, ProxyError)
- [x] `construction/u1-aigateway/functional-design/business-logic-model.md` — request lifecycle, routing, streaming, error flows + **Testable Properties (PBT-01)**
- [x] `construction/u1-aigateway/functional-design/business-rules.md` — validation, defaults, timeouts, error mapping rules

---

## Context (from Application Design)
- AIGateway (FastAPI) binds a container-reachable interface; agents call `http://host.docker.internal:<port>/v1/...`.
- AIGatewayService resolves a route and forwards via UpstreamClient to the upstream (default Ollama `localhost:11434/v1`, model `your-model`).
- Per-agent model/URL override is **designed-for, v2** (v1 = all agents → default upstream + default model).
- Streaming pass-through is required (FR-P6).

---

## Part B — Functional Design Questions

## Question 1 — 에이전트 식별 & 게이트웨이 인증
AI-Gateway가 "어느 에이전트의 호출인지" 식별하고 접근을 통제하는 방식은? (식별값은 로깅·v2 per-agent 오버라이드의 키가 됨)

A) **에이전트별 API 키/베어러 토큰 (권장)** — caduceus가 에이전트 생성 시 토큰을 발급해 그 hermes의 provider `api_key` 로 주입. hermes가 `Authorization: Bearer <token>` 로 호출 → caduceus가 토큰→에이전트 매핑 + 미인증 호출 거부. 표준 OpenAI 패턴.

B) **에이전트별 경로 프리픽스** — `/v1/agents/<name>/...` 로 식별. 토큰 불필요하지만 hermes의 base_url에 에이전트 경로를 넣어야 함.

C) **식별 없음(v1)** — 모두 동일 기본 라우트, 식별/인증 없이 통과(가장 단순, 단 로깅/오버라이드 키 없음).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — "기본 모델" 적용 지점
기본 모델(`your-model`)을 어디서 강제할까요?

A) **에이전트 설정에서 (게이트웨이는 통과) (권장)** — caduceus가 hermes를 기본 모델로 설정하고, 게이트웨이는 요청의 `model` 을 그대로 upstream에 전달. 단순/투명. v2 오버라이드는 게이트웨이가 해당 토큰의 `model`을 재작성하는 방식으로 추가.

B) **게이트웨이에서 주입/재작성** — 게이트웨이가 요청 `model` 을 무시/재작성해 라우트에 따라 결정. 중앙통제는 강하나 요청 변형 로직 필요.

X) Other (please describe after [Answer]: tag below)

[Answer]: hermes의 모델 설정이 "default" 로 되어있으면 caduceus가 default model (your-model) 로 upstream에 전달. 만약 hermes 모델 설정이 따로 있다면, 그대로 전달.

## Question 3 — 프록시 표면(엔드포인트 범위)
게이트웨이가 노출/중계할 OpenAI 엔드포인트 범위는?

A) **제네릭 `/v1/*` 패스스루 리버스 프록시 (권장)** — `chat/completions`(스트리밍 특수처리) 외 `models`, `embeddings` 등 hermes가 호출하는 모든 `/v1/*` 를 일반 전달. 가장 견고(hermes가 무엇을 부르든 동작).

B) **명시적 허용목록** — `/v1/chat/completions` + `/v1/models` 만 지원, 그 외 404. 표면 최소화.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
