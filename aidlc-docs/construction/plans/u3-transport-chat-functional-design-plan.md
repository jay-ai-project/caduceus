# U3 Transport & Chat — Functional Design Plan

**Unit**: U3 — Transport & Chat. **Owns**: FR-C1..C4, RES-4 (timeouts/isolation/circuit-break), RES-5 (process supervision).
**Depends on**: U2 (`Registry.get(name) -> AgentRecord`; `AgentRecord` carries `endpoint / serve_port / serve_auth / session_id / kind`) and, for local restart, the U2 `Provisioner` (`start_serve / stop / start / status`).
**Modules**: `transport/` → `Transport` (abstract) + `ServeTransport`, `ChatService`, `Supervisor`.

Fill `[Answer]:` in Part B (A/B/C… or X=Other), then say "완료".

## Part A — Artifacts to generate (after answers)
- [x] `construction/u3-transport-chat/functional-design/domain-entities.md` — `ChatEvent` (token|message|error|done), `ChatTurn`, `TransportState`, `AgentSupervisionState` (failure count / back-off / circuit), `HealthStatus` (reused from common)
- [x] `construction/u3-transport-chat/functional-design/business-logic-model.md` — `Transport` interface contract + `ServeTransport` flow; `ChatService.chat_stream` (ensure-session → stream → terminate); `Supervisor` sweep/restart/back-off/circuit state machine; **Testable Properties (PBT-01)**
- [x] `construction/u3-transport-chat/functional-design/business-rules.md` — session create/resume rules, per-agent concurrency rule, timeout/isolation (RES-4), restart/circuit policy (RES-5), local-vs-remote capability matrix, fail-fast rule

## Context / key mechanics (from prior design + U2 spike)
- **Transport (C13)**: `open/close`, `chat_stream(session_id, message) -> AsyncIterator[ChatEvent]`, `health() -> HealthStatus`, optional `get_config/set_config` (→ NotSupported), factory `Transport.for_agent(rec)`. v1 impl = **ServeTransport** over the agent's `hermes serve` (published host port from `AgentRecord.serve_port`, auth = `serve_auth` / `HERMES_SERVE_PASSWORD`). FR-C4: an `AcpTransport` can later plug in behind the same interface.
- **ChatService (C7)**: `chat_stream(name, message)` joins Registry + Transport; `_ensure_session(rec)` create-or-resume, persists `session_id` via `Registry.set_session`.
- **Supervisor (C17)**: `start/stop`, `_sweep()` = periodic deep-health sweep → reconnect / restart local agent's `hermes serve` (via U2 Provisioner) / back-off / circuit-break. Never crashes the daemon (RES-4 graceful degradation).
- **Health**: deep checks **never spend an LLM completion** (U2 HealthChecker contract); U3 supplies the injected `transport_healthy(rec)` probe.
- **Capability split (inherited from U2 BR-A10)**: **remote agents cannot be started/stopped/restarted** by caduceus — Supervisor can only probe + mark unhealthy + reconnect for remote; restart applies to **local** agents only.
- **Tech-detail deferral (same convention as U2)**: exact `hermes serve` wire protocol (JSON-RPC/WebSocket frames, session/cancel verbs, auth header) is **validated in Build & Test**; Functional Design stays technology-agnostic and defines the behavior the adapter must satisfy.

---

## Part B — Functional Design Questions

## Question 1 — 세션 자동 복원 실패 시 동작 (FR-C2)
각 에이전트는 1개의 영속 세션을 유지하고 `chat` 마다 자동 복원합니다(`AgentRecord.session_id` 저장). 저장된 `session_id`가 원격/샌드박스 측에 더 이상 존재하지 않을 때(에이전트 재시작·세션 만료·재프로비저닝 등) 어떻게 처리할까요?

A) **투명 재생성 (권장)** — 저장된 세션 복원을 시도하고, 없으면 새 세션을 자동 생성해 `session_id`를 갱신·저장하고 사용자에게는 끊김 없이 진행(로그에 1줄 기록). 장점: "이전 세션 유지" 의도를 best-effort로 지키되 절대 채팅이 막히지 않음. 단점: 과거 대화 맥락이 소실될 수 있음(경고만).

B) **명시적 오류 후 사용자 선택** — 복원 실패 시 채팅을 시작하지 않고 "세션을 찾을 수 없음, 새로 시작할까요?" 오류 이벤트를 반환. 사용자가 다시 명령해야 새 세션 생성.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — 동일 에이전트에 대한 동시 채팅 (세션 무결성)
한 에이전트가 단일 영속 세션을 공유하므로, 같은 에이전트에 대해 두 개의 `chat` 턴이 동시에 진행되면 세션 상태가 꼬일 수 있습니다. v1 정책은?

A) **에이전트당 직렬화 (권장)** — 에이전트별 turn-lock으로 한 번에 하나의 채팅 턴만 활성. 두 번째 요청은 "해당 에이전트가 사용 중" 오류로 빠르게 실패(fail-fast). 단순·안전하며 개인용 도구에 적합.

B) **허용(전송계층에 위임)** — caduceus는 직렬화하지 않고 `hermes serve` 측 동작에 맡김. 구현 단순하나 세션 꼬임 위험을 사용자가 부담.

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 3 — Supervisor 재시작/서킷 정책 (RES-5 / RES-4)
Supervisor가 관리 에이전트를 주기적으로 점검하고, 로컬 에이전트의 `hermes serve`가 죽으면 재시작합니다(원격은 BR-A10에 따라 재시작 불가 → unhealthy 표시 + 재연결만). 구체 정책 기본값은?

A) **표준 기본값 (권장)** — sweep 주기 **30초**; 로컬 에이전트가 연속 **2회** deep-health 실패 시 `hermes serve` 재시작 시도; 재시작은 **지수 백오프**(예: 5s→15s→45s, 상한 ~2분); 백오프 한도 내 **3회** 연속 재시작 실패 시 **서킷 오픈** → 에이전트를 `failed`로 표시하고 자동 재시작 중단(사용자가 `agent start`로 수동 복구 시 리셋). 모든 값은 Settings로 조정 가능.

B) **보수적(최소 개입)** — 자동 재시작 없음; Supervisor는 health만 갱신하고 죽은 에이전트를 unhealthy로 표시. 복구는 전적으로 수동(`agent start`). RES-5의 "자동 재시작"은 후속으로 연기.

C) **공격적(빠른 복구)** — sweep 10초, 연속 1회 실패 시 즉시 재시작, 서킷 오픈 임계 5회. 빠른 복구 대신 잡음/부하 증가.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — 비정상 에이전트로의 chat 요청 처리 (RES-4 fail-fast)
서킷이 열렸거나(`failed`) shallow-health가 실패한 에이전트에게 사용자가 `chat`을 시도하면?

A) **Fail-fast + 명확한 안내 (권장)** — 즉시 명확한 오류 이벤트 반환("에이전트가 비정상/중지됨; `agent ls`로 상태 확인, `agent start`로 복구"). 불필요한 타임아웃 대기를 피함. 단, `creating`/일시적 상태면 짧은 1회 재시도 후 판단.

B) **항상 시도(타임아웃 의존)** — 상태와 무관하게 전송을 시도하고 연결/유휴 타임아웃으로 자연스럽게 실패하게 둠. 단순하지만 사용자 대기 시간이 길어질 수 있음.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — Transport.health() 프로브 수준
deep-health에서 U3가 제공하는 `transport_healthy(rec)` 프로브의 수준은? (U2 계약상 deep check는 LLM completion을 소비하지 않아야 함)

A) **프로토콜 레벨 핸드셰이크만 (권장)** — `hermes serve` 포트에 연결해 프로토콜 핸드셰이크/경량 ping(예: 세션 목록/버전 조회 등 LLM 비소비 호출)만 수행해 살아있음을 확인. LLM 토큰 비용 0, 빠름. 실제 추론 가능 여부는 caduceus upstream 도달성(U1)으로 별도 판정.

B) **실제 미니 추론** — 짧은 프롬프트로 1토큰 생성까지 확인해 end-to-end 추론 가능성까지 검증. 정확하지만 LLM 비용 발생 → U2 deep-health 계약과 충돌(권장 안 함).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6 — 스트림 중단(사용자 취소) 동작 (FR-C1 인터랙티브)
인터랙티브 채팅 중 사용자가 턴을 취소(예: Ctrl-C)하면?

A) **협조적 취소 (권장)** — 진행 중인 스트림을 닫고 가능하면 전송계층에 취소를 전달, `done`(취소 사유 포함) 이벤트로 깔끔히 종료하며 세션은 유지(다음 턴 계속 가능). turn-lock도 해제.

B) **하드 중단** — 스트림만 즉시 끊고 별도 취소 신호는 보내지 않음(전송계층이 알아서 정리). 단순하나 에이전트 측에 좀비 생성 가능.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
