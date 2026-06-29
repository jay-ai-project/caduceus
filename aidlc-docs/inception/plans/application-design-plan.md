# Application Design Plan — Caduceus

**Stage**: INCEPTION → Application Design
**Inputs**: `requirements.md` (approved), `execution-plan.md` (approved)

This plan lists (A) the design artifacts to be produced and (B) a few grounded design questions whose answers shape component boundaries. Please fill the `[Answer]:` tags in Part B, then say "완료".

---

## Part A — Artifacts to Generate (after questions answered)

- [ ] `application-design/components.md` — component definitions, responsibilities, interfaces
- [ ] `application-design/component-methods.md` — method signatures + I/O (business rules deferred to Functional Design)
- [ ] `application-design/services.md` — service/orchestration definitions
- [ ] `application-design/component-dependency.md` — dependency matrix, communication patterns, data flow
- [ ] `application-design/application-design.md` — consolidated design doc
- [ ] Validate completeness/consistency + Resiliency/PBT applicability notes

---

## Proposed Component Overview (for grounding — details come in artifacts)

**Process model**: one `caduceus` **daemon** (hosts AI-Gateway + Control API + registry/supervisor) and a thin **CLI** client.

Components (draft):
- **CLI** (`typer`) — parses commands, calls Control API.
- **Control API** (daemon, `FastAPI`) — agent lifecycle / chat / config / logs / gateway status for the CLI.
- **AI-Gateway** (daemon, `FastAPI`) — OpenAI-compatible `/v1/chat/completions` (streaming) + `/v1/models`; forwards to **UpstreamClient** (default llama-swap).
- **Agent Registry & State Store** — persists agents, per-agent session id, settings.
- **Provisioner (sbx)** — build/use hermes image, create/rm/stop/start sandboxes, publish serve port, configure hermes provider→AI-Gateway, exec/cp.
- **Transport (abstraction) + ServeTransport** — connect to an agent's `hermes serve` (local published port or remote URL): send/stream, get/set config, health. (ACP impl later.)
- **HealthChecker** — shallow/deep checks (agent + upstream).
- **ConfigEditor** — skills/soul/tools/config edits (local via exec/cp).
- **Supervisor** — process supervision / reconnect (resiliency RES-5).

Services (orchestration): **AgentService**, **ChatService**, **ConfigService**, **AIGatewayService**, **Daemon/GatewayService**.

---

## Part B — Design Questions

## Question 1 — CLI ↔ daemon control channel
CLI가 데몬과 통신하는 방식은?

A) **루프백 HTTP (FastAPI) (권장)** — AI-Gateway와 같은 스택 재사용, `--json` 출력·스트리밍(SSE) 쉬움. 127.0.0.1 바인딩.

B) **Unix 도메인 소켓** — 열린 포트 없음(파일 권한으로 접근 제어), 약간 더 안전하지만 스트리밍/구현이 조금 번거로움.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — 상태 저장소(레지스트리/세션 매핑) 형식
caduceus의 로컬 상태(에이전트 목록·세션 id·설정)를 어떻게 저장할까요?

A) **단일 JSON 상태 파일 + 원자적 쓰기 (권장)** — 단순하고 사람이 읽기/편집 가능(NFR-7). 데몬이 접근을 직렬화하므로 동시성 문제 적음.

B) **SQLite** — 동시성·쿼리에 견고, 그러나 무겁고 직접 열람성은 낮음.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — AI-Gateway의 샌드박스 노출 방식 (보안/네트워크)
에이전트(컨테이너)가 caduceus AI-Gateway에 닿는 방식은? (컨테이너→호스트는 `host.docker.internal`)

A) **리스너 분리 (권장)** — Control API는 127.0.0.1 전용(로컬 CLI만), AI-Gateway는 컨테이너에서 도달 가능한 인터페이스(Docker host-gateway)로 별도 바인딩. 제어 평면과 데이터 평면 분리.

B) **단일 리스너** — Control API와 AI-Gateway를 한 리스너로 묶어 host-gateway 인터페이스에 노출(구현 단순, 단 Control API도 컨테이너에서 도달 가능).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — 채팅 세션 소유권 ("이전 세션 유지"를 어디에 둘지)
영속 세션의 실체를 어디에 둘까요?

A) **hermes가 소유 (권장)** — 각 에이전트의 hermes가 자체 세션 저장소(SQLite)로 대화를 보관하고, caduceus는 에이전트별 **세션 id/이름만** 저장해 매 채팅 시 이어가기. 단순하고 hermes 기본 동작과 일치.

B) **caduceus가 소유/중계** — caduceus가 전체 대화 기록을 직접 저장/중계하고 모델 호출 시 매번 컨텍스트를 구성. 이식성은 높지만 hermes 세션과 이중 관리.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
