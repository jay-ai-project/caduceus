# U4 CLI / Daemon / Config — Functional Design Plan

**Unit**: U4 — CLI / Daemon / Config (the **composition root**). **Owns**: FR-G1..G4 (daemon, control API, gateway lifecycle, loopback), FR-E1..E3 (local config edit / remote read-only / reload), FR-L1 (agent logs).
**Depends on**: U1 (`AIGatewayService` ASGI app), U2 (`AgentService`/`Registry`/`Provisioner`/`HealthChecker`), U3 (`ChatService`/`Transport`/`Supervisor`). Wires them all together.
**Already exists** (from U1): `caduceus/common/settings.py` (`Settings`, `Timeouts`, `ensure_configured`), `caduceus/common/logging.py` (redacting logger).

Fill `[Answer]:` in Part B (A/B/C… or X=Other), then say "완료".

## Part A — Artifacts to generate (after answers)
- [x] `construction/u4-cli-daemon-config/functional-design/domain-entities.md` — `CreateSpec`/`RegisterSpec`, `AgentView`, `GatewayStatus`, `ConfigSnapshot`/`ConfigChange`/`ConfigResult`, CLI command surface
- [x] `construction/u4-cli-daemon-config/functional-design/business-logic-model.md` — daemon composition/lifecycle (build apps → run both listeners → start Supervisor → graceful stop), ControlAPI routes ↔ services, ControlAPIClient, CLI handlers, ConfigService/ConfigEditor apply+verify flow, `gateway start` config bootstrap; **Testable Properties (PBT-01)**
- [x] `construction/u4-cli-daemon-config/functional-design/business-rules.md` — lifecycle/lock rules, loopback-only control, config-edit local-vs-remote, restart-on-change, logs streaming, output/exit-code conventions

## Context / key mechanics (from prior design)
- **App Design**: Q1 control = loopback HTTP (FastAPI); Q2 state = JSON; Q3 **split listeners** (Control API `127.0.0.1:9700`, AI-Gateway bridge-IP `:9701`); Q4 **hermes owns session** (caduceus stores `session_id` only).
- **Components** (component-methods): C1 CLI (typer), C2 ControlAPIClient, C3 Daemon/GatewayService, C4 ControlAPI routes, C8 ConfigService, C16 ConfigEditor, C18 Config, C19 Logging.
- **Control API routes** already specified: agents CRUD, stop/start, chat (SSE), config get/put, logs (SSE), `/healthz`, `/status`.
- **Settings**: `upstream_base_url`/`default_model` are REQUIRED (no default); `ensure_configured()` raises with guidance; U4 owns the interactive setup.

---

## Part B — Functional Design Questions

## Question 1 — 데몬 기동 방식 (FR-G2: `gateway start`)
`caduceus gateway start` 의 기본 동작은?

A) **백그라운드 데몬화 기본 + `--foreground` 옵션 (권장)** — 기본은 백그라운드로 분리 실행(자식 프로세스로 detach, stdout→`~/.caduceus/logs/`, PID/lock 파일 기록)하고 즉시 프롬프트 복귀; `--foreground`로 포그라운드 실행. 단일 인스턴스 lock으로 중복 기동 방지. 개인용 CLI 사용감에 적합.

B) **포그라운드 기본** — `start`는 포그라운드로 실행(터미널 점유). 백그라운드 실행은 사용자가 `nohup`/`&`/systemd로 처리. 구현 단순(데몬화 로직 불필요), v1 최소주의.

X) Other (please describe after [Answer]: tag below)

[Answer]: 포그라운드 기본으로 하고, `-d` 옵션으로 백그라운드 데몬화

## Question 2 — 설정 변경 적용 방식 (FR-E3)
로컬 에이전트의 설정(skills/soul/tools/core)을 편집한 뒤 변경을 반영하는 방법은?

A) **항상 serve 재시작 (권장)** — 파일 변경(`sbx exec`/`cp`)을 적용한 뒤 그 에이전트의 `hermes serve`를 재시작해 결정론적으로 반영. U3 Supervisor와 동일한 재시작 경로 재사용, 일관·단순. 짧은 순단 발생(채팅 세션은 hermes가 보존하면 유지; 아니면 다음 턴 투명 재생성 Q1).

B) **핫 리로드 시도 후 필요 시 재시작** — 가능한 변경은 무중단 반영을 시도하고, 불가한 항목만 재시작. 순단 최소화하나 어떤 변경이 리로드 가능한지 hermes 의존 → 복잡/불확실(실제 가능 여부는 Build & Test 확인 필요).

X) Other (please describe after [Answer]: tag below)

[Answer]: B - 일단 무중단 반영으로 하고, 이후에 내가 테스트하다가 재시작 해야되는 항목들 별도로 요청했을때 해당 부분 변경때만 재시작하는걸 쉽게 구현할 수있도록.

## Question 3 — 미설정 upstream 으로 `gateway start` 시 (Settings 필수값)
`upstream_base_url`/`default_model` 가 비어 있을 때 `gateway start` 동작은?

A) **대화형 프롬프트 + 파일 저장 (권장)** — 포그라운드 기동 시 값을 물어보고 `~/.caduceus/config.toml` 에 저장(이후 재사용); 비대화형(백그라운드/CI)이면 명확한 오류+가이드로 실패. env > file > default 우선순위 유지.

B) **오류만(비대화형 일관)** — 항상 즉시 오류로 안내만 하고(프롬프트 없음), 설정은 env 또는 사용자가 직접 만든 config 파일로만. 단순하지만 첫 사용 경험이 번거로움.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — 설정 편집 검증 (AC-6: "샌드박스 내부에서 확인")
설정 적용 후 검증 수준은?

A) **적용 후 read-back 검증 (권장)** — 변경을 쓴 뒤 샌드박스 내부 설정을 다시 읽어 의도한 값이 반영됐는지 확인하고, 재시작 후 health 가 정상으로 돌아오는지 확인해 `ConfigResult` 로 보고. AC-6 충족, 실패 시 명확한 오류.

B) **적용만(검증 없음)** — 쓰기 성공 = 성공으로 간주. 단순하나 AC-6의 "확인" 요건을 약하게 충족.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — `agent config` 의 soul 입력 + 편집 표면
`agent config` 로 편집 가능한 항목과 soul 입력 방식은? (component-methods 기준: `--add-skill`, `--enable-tool/--disable-tool`, `--soul-file`, `--set key=value`)

A) **파일 기반 soul + 나열형 편집 (권장)** — soul 은 `--soul-file <path>`(파일 내용으로 SOUL.md 교체)로만; skills 는 `--add-skill`(+ 제거 옵션), tools 는 `--enable-tool/--disable-tool`, core 는 `--set key=value`. 명확·스크립트 친화적. `--get`(또는 `--json`)으로 현재 스냅샷 조회.

B) **인라인 soul 도 허용** — 위 + `--soul "<text>"` 인라인 입력도 지원. 편의↑이나 셸 이스케이프/대용량 텍스트 부담.

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 6 — CLI 출력 규약
사용자 대상 출력/종료코드 규약은?

A) **사람용 기본 + `--json` 옵션, 비-0 종료코드 (권장)** — 기본은 사람이 읽기 쉬운 표/문장, `--json` 시 기계가공용 JSON. 오류는 stderr + 비-0 종료코드(예: 사용오류 2, 런타임/업스트림 실패 1). `agent ls`/`gateway status` 등에 일관 적용.

B) **항상 JSON** — 모든 출력 JSON 고정(사람 친화성↓, 도구 연동↑). 개인용 대화형 사용에는 부적합.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
