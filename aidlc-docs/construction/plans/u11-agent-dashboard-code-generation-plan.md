# U11 — Agent Dashboard Routing — Code Generation Plan

Baseline: 308 unit+PBT + 4 Playwright e2e green (U10). Spec = u11 requirements + FD
(D1–D9, L1–L6, BR-DB1..16, PBT-U11-1..3). Q3: 마이그레이션/호환 코드 금지.

## Part 2 Steps

- [x] **S1. Models** — `common/models.py`: `AgentRecord.dashboard_port: Optional[int]`,
  `dashboard_password: Optional[str]` (SECRET 주석) + `to_dict`/`from_dict` 반영.
- [x] **S2. DTOs** — `common/dto.py`: `AgentView.dashboard: bool` (+`from_record`:
  `rec.dashboard_port is not None`), `CreateSpec.dashboard: bool = True` (+dict 라운드트립),
  신규 `DashboardCredentials` (username/password/url).
- [x] **S3. Provisioner** — `agents/provisioner.py`: `DASHBOARD_CONTAINER_PORT = 9119`;
  `create(..., publish_dashboard: bool)` → 활성 시 `-p 127.0.0.1::9119` 추가;
  `host_port(container, port: int = CONTAINER_API_PORT)` 일반화 (Protocol 시그니처 포함).
- [x] **S4. Create saga + start refresh** — `agents/service.py`: `create(..., dashboard=True)`
  → password 발급(`mint_token`), dashboard env 3종 (BR-DB1), `publish_dashboard` 전달;
  start 후 `dashboard_port` best-effort 조회 (실패 = 경고 + None, BR-DB3);
  `start()`의 host_port 갱신 블록에서 `dashboard_port`도 갱신 (BR-DB4).
- [x] **S5. Config-restart refresh** — `daemon/wiring.py` restart_serve 경로: endpoint 갱신
  시 `dashboard_port`도 재조회 (BR-DB4).
- [x] **S6. Proxy 헬퍼 (신규 파일)** — `caduceus/daemon/dashboard_proxy.py`: 순수 함수
  `upstream_url(port, raw_path, query) -> str` (D4: 문자열 결합, authority 고정),
  `filter_headers(headers) -> list[tuple]` (D5: RFC-7230 고정 목록 + Connection 지목 토큰),
  `PREFIX_FMT = "/agents/{name}/dashboard"`. PBT 대상이므로 I/O 없음.
- [x] **S7. HTTP 프록시 + 자격증명 라우트** — `daemon/control_api.py`:
  `GET /agents/{name}/dashboard-credentials` (404 시맨틱, BR-DB16);
  `GET /agents/{name}/dashboard` → 308 `…/`;
  `api_route /agents/{name}/dashboard/{path:path}` (전 메서드) — 검증(BR-DB5) →
  X-Forwarded-Prefix 주입 → 공유 httpx AsyncClient(connect=5s, read=None)로
  `send(stream=True)` → status/필터된 헤더/`aiter_raw()` StreamingResponse; 연결 실패 502.
  클라이언트는 app lifespan에서 생성/종료.
- [x] **S8. WS 브리지** — `daemon/control_api.py`:
  `@app.websocket("/agents/{name}/dashboard/{path:path}")` — 검증 실패 시 close(4404);
  `websockets.connect(ws://…, extra_headers={Cookie[, Authorization]},
  subprotocols=<제안 목록>)` 성공 후 accept(협상 subprotocol); 양방향 pump(text/bytes),
  close code 전파, 태스크 정리 (BR-DB11/12).
- [x] **S9. CLI** — `cli/app.py`: `agent create --no-dashboard`;
  신규 `agent dashboard-cred NAME [--json]` (0/2/1 규약); `cli/client.py`:
  CreateSpec.dashboard 전달 + `GET dashboard-credentials`; `cli/render.py`: 자격증명
  human 렌더 (control base 기준 절대 프록시 URL).
- [x] **S10. Web UI** — `webui/assets/app.js`(+필요 시 styles/index): local & dashboard=true
  카드에 "Dashboard" 새 탭 링크(`/agents/<name>/dashboard/`) + 자격증명 버튼 →
  fetch 후 모달 표시/클립보드 복사 (L5).
- [x] **S11. 의존성** — `pyproject.toml`: `websockets>=12` 재도입 (D1).
- [x] **S12. Tests** — CLAUDE.md 위임 프로토콜: **fork subagent**(e2e-test-writer 컨벤션)로
  작성 위임 (불가 시 인라인 fallback, U8 전례):
  unit — proxy 헬퍼(경계 케이스), 프록시 라우트(404/502/308/헤더/스트리밍), 자격증명
  라우트/CLI, saga(dashboard on/off/포트 실패 best-effort), start/restart 포트 갱신,
  fakes 확장(FakeProvisioner.host_port(port), publish 기록);
  PBT — `tests/pbt/test_u11_properties.py`: PBT-U11-1(URL totality),
  PBT-U11-2(hop-by-hop 필터), PBT-U11-3(secret 비노출);
  e2e — Playwright: 카드에 Dashboard 링크/자격증명 버튼 노출.
- [x] **S13. README 동기화** — dashboard 기능 (기본 on, `--no-dashboard`,
  `agent dashboard-cred`, 프록시 URL, 로그인 안내, ADV-1..3 보안 노트).
- [x] **S14. 검증** — 전체 unit+PBT 그린 + e2e 그린; import/entrypoint 확인;
  plan/state/audit 체크박스 갱신.

## DoD
- 전 스텝 [x]; 기존 308+4 → 증가된 수치로 전체 그린; 신규 의존성 websockets만;
- BR-DB15 준수: 마이그레이션/호환 분기 없음 (리뷰 시 grep).
