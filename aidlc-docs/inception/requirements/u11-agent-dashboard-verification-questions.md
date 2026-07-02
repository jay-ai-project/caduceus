# U11 — Agent Dashboard Routing: Verification Questions

**Request**: caduceus가 연결된 hermes agent의 dashboard로 접근 경로를 라우팅.
Web UI agent card에서 dashboard 링크 제공; `http://caduceus-host/<agent-path>/dashboard`
접속 시 실제 hermes agent가 서빙하는 dashboard 페이지에 도달. CORS로 프록시가
불가능하면 단순 링크도 허용.

---

## Spike Findings (hermes 0.17.0 / official image v2026.6.19) — 사실 확인 완료

1. **Dashboard는 별도 서버**: `hermes dashboard` (FastAPI, 기본 포트 9119) —
   `gateway run`(API server :8642)과 별개 프로세스. 현재 caduceus 컨테이너에는 **떠 있지 않음**.
2. **이미지에 s6 슈퍼바이즈 dashboard 슬롯 내장**: env `HERMES_DASHBOARD=true`만 주면
   CMD(`gateway run`)와 **나란히** 자동 기동 (`0.0.0.0:9119`, `HERMES_DASHBOARD_HOST/PORT`로 조정).
   웹 번들은 이미지에 프리빌드되어 있어 npm 불필요.
   → caduceus는 `docker create` 시 env 추가 + `-p 127.0.0.1::9119` 퍼블리시 + host_port 기록만 하면 됨.
   ⚠️ 단, **포트/env는 컨테이너 생성 시에만 지정 가능** → 기존 agent는 컨테이너 재생성 필요.
3. **인증 필수**: 컨테이너 안 0.0.0.0 바인드는 non-loopback → auth gate가 **강제**
   (2026-06 hardening, 우회 불가). zero-infra 방식 = bundled **basic password provider**
   (`HERMES_DASHBOARD_BASIC_AUTH_USERNAME` + `_PASSWORD` env → 로그인 폼 + HMAC 세션 쿠키).
4. **Sub-path 리버스 프록시 네이티브 지원**: 프록시가 `X-Forwarded-Prefix: /agents/<name>/dashboard`
   헤더를 주입하면 hermes가 index.html asset URL 재작성, SPA 런타임 base path
   (`__HERMES_BASE_PATH__`), 쿠키 `Path`, 로그인 리다이렉트, CSS asset까지 모두 처리
   ("mission-control 스타일 배포"가 공식 지원 시나리오). → **CORS 문제 없음** (same-origin).
5. **프록시 구현 난이도**: HTTP + SSE 스트리밍은 기존 control API 패턴으로 무난.
   dashboard의 embedded chat/terminal은 **WebSocket** (`/api/pty`, `/api/ws`) →
   caduceus가 WS 브리지도 프록시해야 완전 동작 (FastAPI WebSocket ↔ 컨테이너 WS 중계).
6. **경로 명칭**: hermes 공식 명칭이 "dashboard" (`hermes dashboard` 명령) →
   `/agents/<name>/dashboard`가 일관성 있음 (caduceus 자체 UI는 `/ui`로 이미 사용 중).

---

## Q1. 라우팅 방식

hermes가 prefix 프록시를 공식 지원하므로 사용자가 원한 경로 라우팅이 가능합니다.
WebSocket 브리지(embedded chat/terminal 탭)가 유일한 추가 복잡도입니다.

- **A (권장)**: **Full same-origin 리버스 프록시** — Control API(:9700)에
  `/agents/{name}/dashboard/{path...}` 라우트 추가, `X-Forwarded-Prefix` 주입,
  HTTP + SSE + **WebSocket 모두 중계**. Web UI agent card 링크는 이 경로로.
  단일 origin, CORS 무관, dashboard 전 기능 동작.
- **B**: **프록시 (HTTP/SSE) + WS 미지원 명시** — 구현 단순화. dashboard의
  embedded chat/terminal 탭만 동작 안 함 (나머지 페이지는 정상). 추후 WS 추가 가능.
- **C**: **단순 링크** — dashboard 포트를 host loopback에 퍼블리시하고 agent card가
  `http://127.0.0.1:<port>/`로 직접 링크 (+ `GET /agents/{name}/dashboard` → 302 리다이렉트
  제공). 프록시 없음, 가장 단순, 전 기능 동작. 단 URL이 caduceus host 경로가 아님.

[Answer]: A

## Q2. Dashboard 활성화 정책 (신규 agent)

dashboard 프로세스는 컨테이너당 메모리를 추가로 사용하며, env/포트는 생성 시에만
지정할 수 있습니다.

- **A (권장)**: **기본 활성화** — 모든 신규 local agent에 dashboard env + 포트 퍼블리시
  포함. 링크가 항상 동작 (개인 로컬 도구 취지에 부합). `agent create --no-dashboard`로 제외.
- **B**: **opt-in** — 기본 비활성. `agent create --dashboard` 지정 시에만 활성화.

[Answer]: A

## Q3. 기존 agent 마이그레이션

이미 생성된 agent 컨테이너에는 dashboard 포트를 추가할 수 없습니다 (docker 제약).

- **A (권장)**: **재생성 경로 제공** — `caduceus agent dashboard enable <name>` (또는
  `agent config --dashboard on`): 컨테이너를 정지→삭제→같은 workspace/config/토큰으로
  재생성(+dashboard env/포트)→재시작. workspace는 bind-mount라 보존됨.
  ⚠️ HERMES_HOME(익명 볼륨)의 세션 히스토리는 유실 — 명령 실행 시 경고 표시.
- **B**: **문서만** — 기존 agent는 delete + create 안내 문구로 대응 (코드 변경 없음).

[Answer]: 기존 환경은 깔끔하게 제거했으므로, 하위 호환성이나 fallback, 마이그레이션에 대해 고려하지 말 것.

## Q4. Dashboard 인증 자격증명

auth gate는 우회 불가이므로 caduceus가 자격증명을 관리해야 합니다.

- **A (권장)**: **agent별 자동 발급** — username = agent 이름, password = caduceus가
  발급한 per-agent secret (AgentRecord에 secret으로 저장, AgentView에는 비노출).
  Web UI agent card / `agent ls --json`이 아닌 **전용 CLI/route로만 조회**
  (`caduceus agent dashboard-cred <name>` + Web UI 링크 옆 "자격증명 복사" 버튼).
- **B**: **공유 password** — gateway config에 단일 dashboard password (`gateway config
  --dashboard-password`). 모든 agent 동일 자격증명, 관리 단순.
- **C**: **agent token 재사용** — 이미 있는 per-agent bearer token을 password로 재사용.
  발급 항목은 안 늘지만, dashboard 로그인 폼에 API 토큰을 입력하는 시맨틱 혼용.

[Answer]: A

## Q5. Remote agent (URL로 register된 agent)

caduceus가 컨테이너를 제어하지 않으므로 dashboard 존재/포트를 알 수 없습니다.

- **A (권장)**: **optional 등록 필드** — `agent register --dashboard-url <url>` (옵션).
  지정 시 agent card에 해당 URL로의 **단순 링크** 표시 (프록시 없음). 미지정 시 링크 없음.
- **B**: **범위 외** — remote agent는 dashboard 링크 미지원 (local만).

[Answer]: B

## Q6. Extensions (이 사이클)

- **A (권장)**: U8과 동일 상속 — Security Baseline = **advisory/non-blocking**
  (인증·프록시·secret 노출 경계가 있으므로), Resiliency = full, PBT = full.
- **B**: U10 이전 기본 — Security = No, Resiliency = full, PBT = full.

[Answer]: A
