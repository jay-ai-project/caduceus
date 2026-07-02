# U11 — Agent Dashboard Routing — Code Summary

## Created
- `caduceus/daemon/dashboard_proxy.py` — 순수 헬퍼: `upstream_url` (authority 고정 문자열
  결합), `filter_headers` (RFC-7230 hop-by-hop 고정 목록 + Connection 지목 토큰, drop_host),
  `prefix_for`, `HOP_BY_HOP`.
- `tests/unit/test_dashboard_proxy.py` — 헬퍼 경계 케이스 + 라우트 (자격증명 200/404×3,
  308+query, 프록시 404/502, **실소켓 passthrough** [X-Forwarded-Prefix 주입·Cookie 전달·
  중복 Set-Cookie 보존], **실 WS echo 서버 대상 브리지 왕복**[text+bytes, path/query/Cookie
  전달], WS 거부, AgentView flag/secret) — 14 tests.
- `tests/pbt/test_u11_properties.py` — PBT-U11-1 (URL totality), -2 (hop-by-hop 필터,
  substring-collision 가드), -3 (secret 비노출, coincidental-substring assume 가드).

## Modified
- `common/models.py` — `AgentRecord.dashboard_port` / `dashboard_password`(SECRET) + 직렬화.
- `common/dto.py` — `AgentView.dashboard`, `CreateSpec.dashboard=True`, `DashboardCredentials`.
- `agents/provisioner.py` — `DASHBOARD_CONTAINER_PORT=9119`, `create(..., publish_dashboard)`
  (`-p 127.0.0.1::9119`), `host_port(container, port=8642)` 일반화.
- `agents/hermes_config.py` — `dashboard_env(username, password)` (HERMES_DASHBOARD 3종).
- `agents/service.py` — create saga: password 발급→env→publish→start 후
  `_refresh_dashboard_port` (best-effort, BR-DB3); `start()`에서도 재조회 (BR-DB4).
- `daemon/wiring.py` — restart_serve reload 경로에서 dashboard_port 재조회 (BR-DB4).
- `daemon/control_api.py` — `GET /agents/{n}/dashboard-credentials`; `…/dashboard` 308;
  `…/dashboard/{path:path}` 전 메서드 스트리밍 프록시 (공유 httpx client connect=5s/
  read=None, `aiter_raw`, raw_headers로 중복 Set-Cookie 보존, X-Forwarded-Prefix 주입,
  404/502 시맨틱); WS 브리지 (`websockets.asyncio.client`, upstream 연결 후 accept,
  subprotocol 협상 전달, 양방향 pump + close 전파); create 라우트에 `spec.dashboard` 배선.
- `cli/{app,client,render}.py` — `agent create --dashboard/--no-dashboard`,
  `agent dashboard-cred NAME [--json]` (404→exit 2), 자격증명 렌더 (절대 URL).
- `webui/assets/{app.js,styles.css}` — 카드 Dashboard 새 탭 링크(+`a.btn` 스타일) + Creds
  버튼 (fetch→표시+클립보드; 스냅샷에 password 없음).
- `pyproject.toml` — **`websockets>=13`** (FD D1의 `>=12`에서 상향: 신 asyncio 클라이언트
  API `additional_headers`가 13+; 설치본 16.0).
- `tests/fakes.py` — FakeProvisioner dashboard_ports/published_dashboard + host_port(port) +
  start 시 재할당; FakeAgentService.create(dashboard=…); FakeControlAPIClient.base_url/
  created_specs/dashboard_credentials.
- `tests/unit/{test_agent_service,test_agent_config,test_cli}.py` — saga on/off/best-effort/
  start-refresh(4), restart-refresh(1), CLI(3) 추가.
- `tests/e2e/{conftest,test_webui_smoke}.py` — demo-agent에 dashboard 시드 + plain-agent,
  링크/버튼 노출 e2e 1건.
- `README.md` — 기능 bullet, Web UI 절 (+보안 노트: env 노출/state.json/세션 휘발 = ADV-1..3),
  CLI 표 (`--no-dashboard`, `dashboard-cred`).

## Deviations from plan
- fork subagent 미가용 (환경에 없음, U8 전례) → 테스트 인라인 작성.
- `websockets>=12` → `>=13` (신 asyncio 클라이언트 필요).
- Starlette 1.3: `app.add_event_handler` 제거됨 → `app.router.add_event_handler`.

## Live defect U11-L1 (Build & Test에서 발견·수정)
- hermes 0.17.0 로그인 페이지의 인라인 스크립트가 절대 `fetch('/auth/password-login')` +
  비prefix `next` 리다이렉트 사용 (업스트림 prefix 지원의 갭 — SPA index는 재작성되지만
  로그인 페이지는 아님) → 프록시 경유 로그인 실패.
- 수정: `dashboard_proxy.rewrite_login_page()` (표적·멱등 치환 2건); 프록시가 text/html
  응답만 버퍼링해 적용 (content-length 재계산), upstream에 `Accept-Encoding: identity`
  강제 (HTML 재작성 가능성 보장; 나머지는 스트리밍 유지). 회귀 테스트 2건 추가 → **339 green**.
- 라이브 검증: 재작성된 로그인 페이지 → 로그인 200 → `/api/auth/me` 인증 →
  SPA index prefix asset 정상.

## Verification
- **337 tests green**: 332 unit+PBT (기존 308 → +24) + 5 Playwright e2e (기존 4 → +1).
- PBT-U11-2가 작성 중 실제 기대값 산정 오류를 즉시 검출 (무작위 목록 내 Connection 헤더의
  지목 토큰) — 구현은 정상, 테스트 기대값 수정.
- entrypoint OK; BR-DB15 grep clean (legacy/migration 분기 없음); node --check OK.
