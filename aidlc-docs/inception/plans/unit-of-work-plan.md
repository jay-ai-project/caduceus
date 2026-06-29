# Unit of Work Plan — Caduceus

**Stage**: INCEPTION → Units Generation (Part 1: Planning)
**Inputs**: requirements.md, application-design/* (approved)

Fill the `[Answer]:` tags in Part B, then say "완료".

---

## Part A — Artifacts to Generate (Part 2, after approval)

- [x] `application-design/unit-of-work.md` — unit definitions, responsibilities, **code organization strategy** (greenfield)
- [x] `application-design/unit-of-work-dependency.md` — unit dependency matrix + build/integration order
- [x] `application-design/unit-of-work-story-map.md` — **requirement→unit** map (User Stories were skipped, so FRs are mapped instead)
- [x] Validate unit boundaries, ensure every FR is assigned to a unit

---

## Proposed Units (from Application Design — for grounding)

| Unit | Modules / components | Owns FRs |
|---|---|---|
| **U1 — AI-Gateway** | AIGateway, AIGatewayService, UpstreamClient | FR-P1..P6 |
| **U2 — Agent Registry & Provisioner** | AgentService, Registry/StateStore, Provisioner, ImageBuilder, HealthChecker | FR-A1..A6, FR-L2, hermes image |
| **U3 — Transport & Chat** | Transport/ServeTransport, ChatService, Supervisor | FR-C1..C4, RES-4/RES-5 |
| **U4 — CLI / Daemon / Config** | CLI, ControlAPIClient, Daemon/GatewayService, ControlAPI, ConfigService, ConfigEditor, Config, Logging | FR-G1..G4, FR-E1..E3, FR-L1 |

These are **logical modules of one deployable** (the caduceus daemon+CLI), not separate services.

---

## Part B — Decomposition Questions

## Question 1 — 코드 구성(Code Organization)
caduceus는 단일 배포물(데몬+CLI)입니다. 코드 구성을 어떻게 할까요?

A) **단일 Python 패키지(모노레포) + 단위별 모듈 (권장)** — 하나의 `caduceus/` 패키지 안에 `aigateway/`, `agents/`, `transport/`, `cli/`, `daemon/`, `config/`, `common/` 모듈로 분리. `pyproject.toml` 하나, `pipx` 설치. 예시 구조:
```
caduceus/                  # repo root
  pyproject.toml
  caduceus/                # package
    cli/  daemon/  aigateway/  agents/  transport/  config/  common/
  images/hermes/Dockerfile
  tests/  (unit/ integration/ pbt/)
```

B) **다중 패키지** — 단위별로 별도 설치 패키지로 분리(예: caduceus-core, caduceus-cli). 경계는 뚜렷하나 단일 도구에는 과함.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — 단위 분할 입도(Granularity)
Construction을 어떤 단위로 진행할까요?

A) **4개 단위 유지 (권장)** — U1·U2·U3·U4. 의존성 순서대로 점진 구현/검증.

B) **2개로 통합** — 백엔드(U1+U2+U3) + 프론트/오케스트레이션(U4).

C) **1개 단위** — 전체를 한 단위로(설계 1회 + 코드생성 1회). 게이트 최소, 입도 최저.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — Construction 루프 형태 (게이트 수에 직접 영향)
표준 워크플로우는 "단위마다" 설계 스테이지를 반복합니다. caduceus는 하나의 응집된 앱이라 횡단(NFR/인프라) 설계는 공유됩니다. 어떻게 진행할까요?

A) **통합 설계 + 점진 빌드 (권장)** — Functional Design, NFR Requirements, NFR Design, Infrastructure Design을 **전체 시스템 기준 1회씩**(단위별 세부 포함) 수행 → 이후 **Code Generation은 단위별(U1→U2→U3→U4)** → Build & Test. 승인 게이트를 줄이면서 점진적·검증가능한 구현 유지.

B) **완전 단위별 루프** — 각 단위마다 Functional/NFR/Infra 설계를 반복한 뒤 그 단위 코드 생성. 가장 엄격하지만 게이트가 크게 늘어남.

C) **최소** — 단위 1개(Q2=C) 전제로 설계 1회 + 코드생성 1회.

X) Other (please describe after [Answer]: tag below)

[Answer]: B
