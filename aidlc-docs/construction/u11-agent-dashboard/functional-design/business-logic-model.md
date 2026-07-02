# U11 — Functional Design (light) — Business Logic Model

## L1 — Dashboard-enabled provisioning (AgentService.create / _provision)

```
create(name, ..., dashboard=True):
  password = mint_token() if dashboard else None
  rec = AgentRecord(..., dashboard_password=password)   # dashboard_port는 start 후
  saga _provision:
    env = api_server_env(token) + OPENAI_API_KEY
    if dashboard: env += {HERMES_DASHBOARD, ..USERNAME=name, ..PASSWORD=password}
    provisioner.create(cn, tag, env, runtime, publish_dashboard=dashboard)
    ... write_config → start ...
    rec.host_port      = provisioner.host_port(cn)                      # 8642 (기존)
    rec.dashboard_port = provisioner.host_port(cn, DASHBOARD_CONTAINER_PORT) if dashboard
                         # 실패(None) → 경고 로그 + dashboard 없이 계속 (best-effort:
                         # dashboard 결함이 agent 자체를 실패시키지 않는다, BR-DB11)
    ... await_ready → warm → health ...
```

- `agent start`(재시작) 후에도 host 포트는 재할당된다 — 기존 start 경로가 `host_port`를
  갱신하는 지점에서 `dashboard_port`도 같이 재조회한다 (레코드에 password가 있으면
  dashboard 컨테이너 포트가 존재).
- `agent config`의 restart_serve reload 경로(U10/R9)도 동일하게 dashboard_port를 갱신.

## L2 — HTTP/SSE 리버스 프록시 (control_api)

```
ANY /agents/{name}/dashboard/{path:path}:
  rec = registry.get(name)
  rec 없음                          → 404 "no such agent"
  remote 또는 dashboard_port 없음   → 404 "agent has no dashboard"
  upstream = "http://127.0.0.1:{rec.dashboard_port}" + normalize(path) + "?" + query
  req_headers = client headers − hop_by_hop − {host} + {X-Forwarded-Prefix: prefix}
  httpx 스트리밍 send (connect=5s, read=None)
    연결 실패/타임아웃 → 502 (원인 detail)
  응답: status 그대로, headers − hop_by_hop, body = aiter_raw() 스트리밍
GET /agents/{name}/dashboard  → 308 → "/agents/{name}/dashboard/"
```

- `normalize(path)`: 원본 요청의 raw path에서 prefix 이후 부분을 사용하되, 항상 정확히
  하나의 leading `/`을 갖도록 함 (빈 path → `/`). query string은 원본 그대로.
- 프록시 라우트는 caduceus 인증 없음 (hermes auth gate + 127.0.0.1 바인드가 경계).

## L3 — WebSocket 브리지 (control_api)

```
WS /agents/{name}/dashboard/{path:path}:
  rec 검증은 L2와 동일 (불가 시 accept 전 close(4404))
  upstream = "ws://127.0.0.1:{port}" + normalize(path) + "?" + query
  websockets.connect(upstream,
      extra_headers={Cookie, Authorization(있을 때)},
      subprotocols=<클라이언트 제안 목록>)
    실패 → client close(1014)              # bad gateway 의미
  client.accept(subprotocol=<협상 결과>)
  pump A: client → upstream (text/bytes)
  pump B: upstream → client (text/bytes)
  어느 쪽이든 종료 → close code 전파, 두 태스크 취소/정리 (leak 금지)
```

## L4 — 자격증명 조회

```
GET /agents/{name}/dashboard-credentials:
  rec 없음 / password 없음(비활성·remote) → 404
  → {username: rec.name, password: rec.dashboard_password,
     url: "/agents/{name}/dashboard/"}
CLI: caduceus agent dashboard-cred NAME [--json]
  human: 프록시 절대 URL(control base 기준) + username + password 출력
  exit codes 0/2/1 규약 준수 (없음/비활성 → 2)
```

## L5 — Web UI (assets/app.js + index.html)

- agent card: `view.dashboard && kind == local`이고 lifecycle이 running/healthy 계열일 때
  "Dashboard" 링크 (`/agents/<name>/dashboard/`, `target=_blank`) + "자격증명" 버튼.
- 자격증명 버튼: `GET /agents/<name>/dashboard-credentials` → 모달 표시 + 복사 버튼.
  스냅샷/이벤트 payload에는 password가 없으므로 조회 시점에만 fetch.

## L6 — Shutdown 상호작용 (기존 메커니즘에 위임)

- 열린 프록시 스트림/WS 연결은 uvicorn `timeout_graceful_shutdown=5`(U10-L1)가 종료를
  보장 — U11은 추가 훅 없이 이 경계 안에서 동작해야 하고, Build & Test에서
  "프록시 스트림/WS 열린 채 `gateway stop`" 시나리오를 검증한다.

## PBT 대상 (full)

- **PBT-U11-1 (proxy URL totality)**: 임의 path(빈 값, `..`, `//`, %-인코딩, 유니코드)에
  대해 결합 결과가 항상 `http://127.0.0.1:<port>/`로 시작하고 예외 없음.
- **PBT-U11-2 (hop-by-hop 필터)**: 임의 헤더 집합(+Connection이 지목하는 임의 토큰)에
  대해 필터 후 hop-by-hop 부재 & end-to-end 보존.
- **PBT-U11-3 (secret 비노출)**: 임의 AgentRecord(w/ dashboard_password)의
  AgentView/이벤트 스냅샷 직렬화에 password 문자열 부재. (기존 record 라운드트립
  프로퍼티는 새 필드를 자동 포함.)
