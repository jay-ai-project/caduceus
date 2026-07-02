# U11 — Functional Design (light) — Domain Entities

## Inline Decisions (adaptive — no separate question round; requirements are specific)

- **D1 WS 의존성**: WS 브리지의 클라이언트 측은 **`websockets>=12` 런타임 의존성 재도입**
  (U8에서 제거했던 것 — 명시적 재도입 결정). 서버 측은 FastAPI/Starlette 내장 WebSocket.
  (대안 aiohttp는 무겁고, raw 구현은 부적절.)
- **D2 프록시 클라이언트**: daemon 수명의 공유 `httpx.AsyncClient`
  (`Timeout(connect=5, read=None, write=None, pool=None)`), `build_control_app`에서 생성,
  app shutdown 시 close. 응답은 `send(..., stream=True)` + `aiter_raw()`로 중계
  (Accept-Encoding 투명 전달 → content-encoding/length 왜곡 없음).
- **D3 라우트 배치**: `GET /agents/{name}/dashboard-credentials`(고정 리터럴) +
  `/agents/{name}/dashboard` (→ `…/dashboard/` 308) +
  `ANY /agents/{name}/dashboard/{path:path}` (프록시) +
  `WS /agents/{name}/dashboard/{path:path}` (브리지). 리터럴 세그먼트가 달라 충돌 없음.
- **D4 URL 결합**: `urljoin` 금지. `base = http://127.0.0.1:<dashboard_port>` 뒤에
  항상 단일 `/`로 시작하도록 정규화한 raw path(+원본 query string)를 **문자열 결합**.
  path가 무엇이든 authority는 base 고정 (PBT-U11-1).
- **D5 헤더 규칙**: RFC 7230 hop-by-hop 고정 목록(connection, keep-alive,
  proxy-authenticate, proxy-authorization, te, trailers, transfer-encoding, upgrade)
  **+ Connection 헤더가 지목한 토큰**을 양방향 제거. 요청에서 `host` 제거(httpx가 재설정),
  `X-Forwarded-Prefix: /agents/<name>/dashboard` 주입. 쿠키/기타 end-to-end 헤더는 투명 전달.
- **D6 WS 브리지**: upstream(`ws://127.0.0.1:<port>/<path>?<query>`) 연결 성공 후에만
  클라이언트 accept (subprotocol은 클라이언트 제안 목록 전달, 협상 결과 반영;
  Cookie/Authorization 헤더 전달). 양방향 pump 태스크 2개(text/bytes 모두),
  한쪽 종료 시 close code 전파 + 반대쪽 종료 + 태스크 정리.
- **D7 password 발급**: 기존 `tokens.mint_token()` 재사용.
- **D8 provisioner**: `DASHBOARD_CONTAINER_PORT = 9119` 상수; `create(...)`에
  dashboard publish 여부 전달(활성 시 `-p 127.0.0.1::9119` 추가);
  `host_port(container, port=CONTAINER_API_PORT)`로 **일반화**해 start 후
  dashboard host port도 동일 함수로 읽음 (U8-D3 순서 준수).
- **D9 CreateSpec**: `dashboard: bool = True` 추가; CLI `agent create --no-dashboard`;
  Web UI Add-Agent 모달 체크박스(기본 on).

## Entity / DTO Changes

### AgentRecord (`common/models.py`)
| 필드 | 타입 | 의미 |
|---|---|---|
| `dashboard_port` | `Optional[int]` (default None) | 컨테이너 9119에 매핑된 host loopback 포트. None = dashboard 비활성. |
| `dashboard_password` | `Optional[str]` (default None) | basic-auth password. **SECRET** — serve_auth와 동일 취급 (AgentView/이벤트/로그 비노출). |

- `to_dict`/`from_dict` 라운드트립에 두 필드 포함 (기존 PBT 라운드트립 프로퍼티가 자동 커버).
- Q3: 구 state.json tolerant-read 분기 없음 — `from_dict`는 `d.get(...)` 기본값만 사용
  (이는 dataclass 기본값이지 마이그레이션 코드가 아님).

### AgentView (`common/dto.py`)
| 필드 | 타입 | 의미 |
|---|---|---|
| `dashboard` | `bool` (default False) | dashboard 활성 여부 (`rec.dashboard_port is not None`). 링크 표시 판단용. |

### CreateSpec (`common/dto.py`)
| 필드 | 타입 | 의미 |
|---|---|---|
| `dashboard` | `bool` (default True) | 생성 시 dashboard 활성화 여부. |

### DashboardCredentials (신규, `common/dto.py`)
```
{ "username": str, "password": str, "url": str }   # url = "/agents/<name>/dashboard/"
```
- `GET /agents/{name}/dashboard-credentials` 응답 및 CLI 렌더 전용. 다른 어떤 payload에도
  password가 실리지 않는다.

## Container Env (provision 시, dashboard 활성일 때만)
```
HERMES_DASHBOARD=true
HERMES_DASHBOARD_BASIC_AUTH_USERNAME=<agent name>
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=<minted secret>
```
(비활성이면 세 env 및 9119 포트 퍼블리시 전부 생략.)
