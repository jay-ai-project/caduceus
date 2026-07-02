# U11 — Agent Dashboard Routing — Requirements

## Intent Analysis
- **User request**: caduceus에 연결된 hermes agent의 dashboard로 접근할 수 있는 경로를
  caduceus가 라우팅. Web UI의 각 agent card에서 dashboard 링크를 제공하고,
  `http://caduceus-host/agents/<name>/dashboard` 접속 시 실제 hermes agent가 서빙하는
  dashboard 페이지에 도달해야 함. (CORS로 프록시가 불가하면 단순 링크 fallback 허용 —
  스파이크 결과 프록시가 공식 지원되므로 fallback 불필요.)
- **Request type**: Enhancement (brownfield, additive).
- **Scope**: `caduceus/agents` (provisioner env/port, models, service), `caduceus/daemon`
  (control_api proxy + WS bridge), `caduceus/cli` (create flag, credential 조회),
  `caduceus/webui` (agent card 링크 + 자격증명 버튼), `caduceus/common` (models/dto).
- **Complexity**: Moderate — 프록시(HTTP/SSE)는 기존 패턴, WS 브리지가 신규 메커니즘.
- **Cycle**: U11 (follows U1–U10). **Extensions**: Security Baseline = **advisory/non-blocking**,
  Resiliency = Yes (full), PBT = Yes (full).

## Confirmed Decisions (from verification questions)
- **Q1 = A** — **Full same-origin 리버스 프록시**: Control API(:9700)에
  `/agents/{name}/dashboard[/{path}]` 라우트, `X-Forwarded-Prefix` 주입,
  HTTP + SSE + **WebSocket 모두 중계**. CORS 무관 (single origin).
- **Q2 = A** — 신규 local agent는 dashboard **기본 활성화** (`agent create --no-dashboard`로 제외).
- **Q3 (user-directed)** — **하위 호환성 / fallback / 마이그레이션 일절 고려하지 않음.**
  기존 환경은 깨끗이 제거됨. 기존 AgentRecord/컨테이너와의 호환 코드, 상태 마이그레이션,
  "dashboard 없는 구세대 agent" 경로를 만들지 말 것.
- **Q4 = A** — **agent별 자격증명 자동 발급**: username = agent 이름, password = caduceus가
  발급한 per-agent secret. AgentRecord에 secret으로 저장, AgentView/`agent ls`에는 비노출.
  전용 CLI/route로만 조회 + Web UI "자격증명 복사" 버튼.
- **Q5 = B** — Remote agent(URL register)는 dashboard 범위 외 (링크/프록시 없음).
- **Q6 = A** — Security advisory(non-blocking) + Resiliency full + PBT full.

## Spike Facts (설계 전제 — hermes 0.17.0 / image v2026.6.19)
- 공식 이미지의 s6 dashboard 슬롯: `HERMES_DASHBOARD=true` env로 CMD(`gateway run`)와 병행
  기동, 기본 `0.0.0.0:9119` (`HERMES_DASHBOARD_HOST/PORT` env). 웹 번들 프리빌드 내장.
- 컨테이너 내 non-loopback 바인드 → auth gate 강제. basic password provider는
  `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` + `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` env로 활성화
  (로그인 폼 + HMAC 세션 쿠키; secret 미설정 시 프로세스 재시작마다 세션 무효 — 허용).
- `X-Forwarded-Prefix` 프록시 공식 지원: index.html asset 재작성, `__HERMES_BASE_PATH__`,
  쿠키 `Path`, 로그인 리다이렉트, CSS asset 인터셉트 모두 hermes 측이 처리.
- 0.0.0.0 바인드 시 hermes host-header 검증은 any-host 허용 → 프록시 Host 헤더 이슈 없음.
- WebSocket 엔드포인트: `/api/pty`, `/api/ws` (embedded chat/terminal) — 프록시가 WS 중계 필요.

---

## Functional Requirements

### FR-U11-1 — Dashboard-enabled provisioning (default on)
- `agent create`는 기본으로 dashboard를 활성화해 컨테이너를 생성한다:
  - env: `HERMES_DASHBOARD=true`, `HERMES_DASHBOARD_BASIC_AUTH_USERNAME=<agent name>`,
    `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=<minted per-agent secret>`.
  - 포트: `-p 127.0.0.1::9119` (API 포트 8642 퍼블리시와 병행) — Docker가 할당한 host
    loopback 포트를 **start 후** 읽어 `AgentRecord.dashboard_port`에 기록 (U8-D3 교훈:
    호스트 포트는 start 후에만 확정).
- `agent create --no-dashboard` 지정 시 dashboard env/포트를 완전히 생략하고
  `dashboard_port = None`으로 기록한다.
- Web UI의 "Add Agent" 모달도 동일 기본값(활성화)을 따른다 (체크박스는 선택 사항).

### FR-U11-2 — AgentRecord / AgentView 모델
- `AgentRecord`에 추가: `dashboard_port: Optional[int]` (없으면 비활성),
  `dashboard_password: Optional[str]` (**secret** — serve_auth와 동일 취급).
- `AgentView`에 추가: `dashboard: bool` (활성 여부만). **password는 AgentView,
  `agent ls`(--json 포함), 로그, 이벤트 스트림 어디에도 노출 금지.**
- Q3에 따라 구 스키마 tolerant-read/마이그레이션 코드는 작성하지 않는다.

### FR-U11-3 — Same-origin 리버스 프록시 (HTTP + SSE)
- Control API(127.0.0.1:9700)에 프록시 라우트를 추가한다:
  - `GET /agents/{name}/dashboard` → `…/dashboard/`로 308 (trailing-slash 정규화).
  - `ANY /agents/{name}/dashboard/{path:path}` → `http://127.0.0.1:<dashboard_port>/<path>`.
- 프록시는 모든 HTTP 메서드를 지원하고, 요청/응답 본문을 **스트리밍**으로 중계한다
  (SSE 무기한 응답 포함 — read timeout 없음, connect timeout은 유한).
- 요청에 `X-Forwarded-Prefix: /agents/<name>/dashboard`를 주입한다 (hermes가 base path
  처리). hop-by-hop 헤더(Connection, Keep-Alive, Transfer-Encoding, Upgrade 등)는
  RFC 7230에 따라 양방향에서 제거하고, 나머지 헤더(쿠키 포함)는 투명하게 전달한다.
- 대상 agent가 없으면 404, remote agent이거나 `dashboard_port`가 없으면 명확한 detail의
  404, 컨테이너 미기동/연결 실패면 502(+원인 detail)를 반환한다.
- 프록시 라우트는 caduceus 자체 토큰 인증을 요구하지 않는다 — 인증은 hermes dashboard의
  auth gate(로그인 폼)가 담당하고, 노출 경계는 Control API의 127.0.0.1 바인드가 담당한다.

### FR-U11-4 — WebSocket 브리지
- 프록시 prefix 아래로 들어오는 WebSocket 업그레이드 요청(`/api/pty`, `/api/ws` 등 경로
  불문)은 컨테이너의 dashboard WS로 **양방향 중계**한다 (text/binary 프레임 모두).
- 어느 한쪽이 닫히면 반대쪽도 닫고 자원을 정리한다 (leak 금지). 브리지 실패는 해당 WS
  연결만 실패시키고 daemon/다른 연결에 영향을 주지 않는다.

### FR-U11-5 — Web UI 통합
- 각 **local** agent card에 dashboard 링크를 표시한다 (`/agents/<name>/dashboard/` 로,
  새 탭). `dashboard=false`인 agent와 remote agent에는 링크를 표시하지 않는다.
- 링크 옆에 "자격증명" 액션 제공: 클릭 시 전용 route에서 username/password를 조회해
  표시/클립보드 복사 (dashboard 이벤트/스냅샷 payload에는 포함하지 않는다).

### FR-U11-6 — 자격증명 조회 (전용 경로)
- Control API: `GET /agents/{name}/dashboard-credentials` → `{username, password, url}`
  (agent 없음/비활성/remote → 404). 이 route 응답 외에는 password가 어떤 API에도
  실리지 않는다.
- CLI: `caduceus agent dashboard-cred <name>` — username/password/프록시 URL을 출력
  (`--json` 지원, exit code 규약 0/2/1 준수).

## Non-Functional Requirements

### NFR-U11-1 — Secret 취급 (Security advisory 연계)
- `dashboard_password`는 serve_auth와 동일한 secret 규약: state.json에는 저장하되
  AgentView/로그/이벤트에 비노출, 로그 redaction 적용.
- 자격증명 env가 `docker inspect`로 노출되는 점(로컬 단일 사용자 머신 전제)은 **advisory**로
  기록하고 차단하지 않는다 (Security Baseline non-blocking 모드).
- 프록시/자격증명 노출 경계 = Control API 127.0.0.1 바인드 (기존과 동일). 0.0.0.0 확대는
  본 사이클 범위 외.

### NFR-U11-2 — Resiliency
- 프록시 connect timeout 유한(예: 5s), 스트리밍 read는 무제한(SSE/WS 특성) — 단 daemon
  graceful shutdown 시 열린 프록시/WS 연결이 종료를 막지 않아야 한다
  (U10-L1 교훈: `timeout_graceful_shutdown` 하에서 정리).
- dashboard 프로세스 다운은 프록시 502로 표면화될 뿐, agent health(:8642 기준)와
  Supervisor 동작에는 영향을 주지 않는다.
- 프록시/브리지 예외는 해당 요청/연결에 국한 (fault isolation).

### NFR-U11-3 — PBT (full)
- **PBT-U11-1**: 프록시 경로 결합 totality — 임의의 `{path}` (빈 문자열, `..`, 인코딩 문자
  포함)에 대해 upstream URL이 항상 `http://127.0.0.1:<port>/` 아래로만 결합되고 예외가
  없다 (path traversal로 다른 origin/포트가 나올 수 없음).
- **PBT-U11-2**: hop-by-hop 헤더 필터 — 임의 헤더 집합에 대해 필터 후 hop-by-hop 헤더가
  전무하고, end-to-end 헤더는 보존된다.
- **PBT-U11-3**: secret 비노출 — 임의 AgentRecord(w/ dashboard_password)에 대해
  AgentView 직렬화/이벤트 payload에 password 문자열이 등장하지 않는다.

## Out of Scope
- Remote agent dashboard (Q5=B).
- 기존 agent/구 스키마 호환·마이그레이션 (Q3 — clean environment).
- Control API의 비루프백 노출, dashboard 자동 로그인(SSO)·세션 위임.
- hermes dashboard 자체 기능 수정.
