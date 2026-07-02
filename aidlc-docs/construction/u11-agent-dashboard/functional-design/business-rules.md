# U11 — Functional Design (light) — Business Rules

## Provisioning
- **BR-DB1**: local `agent create`는 기본으로 dashboard를 활성화한다. `--no-dashboard`
  (CreateSpec.dashboard=false) 시 dashboard env 3종과 9119 포트 퍼블리시를 **전부 생략**하고
  `dashboard_port=None`, `dashboard_password=None`으로 기록한다.
- **BR-DB2**: dashboard password는 agent마다 `mint_token()`으로 발급하며 AgentRecord에만
  저장한다. AgentView, `/api/events` 스냅샷, `agent ls`(--json 포함), 로그 어디에도
  노출되지 않는다 (serve_auth와 동일 규약).
- **BR-DB3**: dashboard host 포트는 컨테이너 **start 후** 조회한다 (U8-D3). 조회 실패는
  경고 로그 + `dashboard_port=None`으로 계속한다 — dashboard 결함이 agent 생성을
  실패시키지 않는다 (best-effort).
- **BR-DB4**: `agent start` / config restart 등 컨테이너가 재시작되는 모든 경로는
  `host_port`를 갱신할 때 `dashboard_port`도 함께 갱신한다.

## Proxy
- **BR-DB5**: 프록시는 `rec.dashboard_port`가 있는 local agent에만 동작한다. 그 외:
  agent 없음 → 404 "no such agent"; remote/비활성 → 404 "agent has no dashboard".
  upstream 연결 실패/타임아웃 → 502(+원인 detail).
- **BR-DB6**: 모든 프록시 요청에 `X-Forwarded-Prefix: /agents/<name>/dashboard`를
  주입한다 (정확히 이 값, trailing slash 없음).
- **BR-DB7**: RFC 7230 hop-by-hop 헤더(고정 목록 + Connection이 지목한 토큰)는 요청/응답
  양방향에서 제거하고, 나머지 헤더(쿠키 포함)는 무변조 전달한다. 요청 `Host`는 제거한다.
- **BR-DB8**: 프록시 응답 본문은 스트리밍으로 중계한다 (SSE 등 무기한 응답 지원 —
  read timeout 없음, connect timeout 5s 유한).
- **BR-DB9**: `GET /agents/{name}/dashboard` (no trailing slash) → 같은 URL + `/`로 308.
- **BR-DB10**: 프록시/자격증명 라우트는 caduceus 자체 인증을 추가하지 않는다 — 인증은
  hermes dashboard auth gate, 노출 경계는 Control API의 127.0.0.1 바인드.

## WebSocket
- **BR-DB11**: WS 브리지는 text/bytes 프레임을 양방향 무변조 중계하고, 한쪽 종료 시
  close code를 반대쪽에 전파하며 두 pump 태스크를 정리한다 (연결/태스크 leak 금지).
- **BR-DB12**: 브리지 실패(연결 불가, 프레임 오류)는 해당 WS 연결에 국한된다 — daemon,
  다른 프록시/브리지 연결, agent health에 영향 없음.

## Resiliency / Health
- **BR-DB13**: dashboard 프로세스 다운은 프록시 502로만 표면화된다. agent health는
  계속 :8642 기준이며 Supervisor 동작에 영향을 주지 않는다.
- **BR-DB14**: 열린 프록시/WS 연결은 daemon graceful shutdown을 막지 않는다
  (`timeout_graceful_shutdown=5` 경계 내 종료 — Build & Test 검증 항목).

## Scope 규율
- **BR-DB15 (Q3)**: 하위 호환/fallback/마이그레이션 코드 금지 — 구 스키마 분기,
  "dashboard 없는 구세대 컨테이너" 감지, sbx 시대 잔재 참조를 추가하지 않는다.
- **BR-DB16 (Q5)**: remote agent에는 dashboard 링크/프록시/자격증명이 없다 (조회 시 404).

## Security (advisory — non-blocking, 기록만)
- **ADV-1**: 자격증명 env는 `docker inspect`로 노출됨 (로컬 단일 사용자 머신 전제 수용).
- **ADV-2**: `dashboard_password`는 state.json(0600 규약)에 평문 저장 — serve_auth/token과
  동일한 기존 취급.
- **ADV-3**: dashboard의 HMAC 세션 secret 미설정 → 컨테이너 재시작 시 세션 무효
  (재로그인 필요) — 수용.
