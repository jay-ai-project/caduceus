# U2 Agent Registry & Provisioner — Functional Design Plan

**Unit**: U2 — Agent Registry & Provisioner. **Owns**: FR-A1..A6, FR-L2 (+ hermes image, built in U2 Infra).
**Depends on**: U1 (agents are configured to use the AI-Gateway URL + a caduceus-minted token).

Fill `[Answer]:` in Part B, then say "완료".

## Part A — Artifacts to generate (after answers)
- [x] `construction/u2-registry-provisioner/functional-design/domain-entities.md` — AgentRecord (+ state machine), AgentKind, SandboxInfo, AgentToken, ProvisionSpec, HealthStatus, ImageRef
- [x] `construction/u2-registry-provisioner/functional-design/business-logic-model.md` — create / register / list / remove / stop / start / health flows + **Testable Properties (PBT-01)** incl. stateful registry PBT (PBT-06)
- [x] `construction/u2-registry-provisioner/functional-design/business-rules.md` — name validation, state transitions, token minting, hermes provider config rule, health criteria, rollback

## Context / key mechanics (from prior design + spike)
- **create (local)**: ensure image → `sbx create shell -t <image> --name <sbx-name>` → publish hermes serve port (`sbx ports`) → configure agent hermes provider (base_url = caduceus AI-Gateway advertise URL, api_key = minted token, model = `default` sentinel) → start `hermes serve` → mint+store token → register `AgentRecord` → verify health → (rollback on failure).
- **register (remote)**: validate endpoint reachable → store `AgentRecord(kind=remote, endpoint, [token])`.
- **Registry**: single JSON state file at `~/.caduceus/state.json`, atomic writes (from App Design Q2).
- **Health (FR-L2)**: shallow = transport endpoint/sandbox reachable; deep = hermes responsive (via transport, U3) + caduceus upstream reachable (no LLM spend).

---

## Part B — Functional Design Questions

## Question 1 — 에이전트 이름 ↔ sbx 샌드박스 이름
caduceus 에이전트 이름과 실제 sbx 샌드박스 이름의 관계는?

A) **프리픽스로 네임스페이싱 (권장)** — 사용자는 `<name>` 으로 부르지만 실제 sbx 샌드박스는 `cad-<name>` 로 생성. 장점: `ls` 가 caduceus 관리 샌드박스만 필터링, 다른 sbx 샌드박스와 충돌/혼동 방지.

B) **그대로 사용** — sbx 샌드박스 이름 = `<name>`. 단순하지만 비-caduceus 샌드박스와 구분 불가.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — 원격 에이전트의 LLM 라우팅 (v1)
요구사항상 원격 에이전트도 "기본적으로 caduceus 경유"지만, v1에서는 원격 hermes 설정이 **읽기 전용**(App Design Q5=A)이라 caduceus가 원격 hermes를 자동 구성할 수 없습니다. v1 동작을 어떻게 할까요?

A) **토큰 발급 + 안내 (권장)** — `register` 시 caduceus가 토큰을 발급하고 AI-Gateway URL을 함께 안내. 사용자가 원격 hermes를 그 base_url+토큰으로 직접 설정하면 caduceus 경유가 됩니다(원격 측 1회 수동). caduceus는 토큰을 등록해 AI-Gateway 인증에 사용. *주의: 진짜 원격 호스트라면 AI-Gateway가 그 호스트에서 도달 가능한 인터페이스에 바인딩되어야 함(설정값).*

B) **v1은 원격 직접 호출** — 원격 에이전트는 자신의 LLM을 직접 호출(caduceus 미경유), caduceus 경유 프록시는 로컬 에이전트에만 v1 적용. 원격 경유는 후속(원격 구성 지원과 함께).

X) Other (please describe after [Answer]: tag below)

[Answer]: A
