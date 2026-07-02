# U10 — Review Remediation Execution Plan (2026-07-02)

**목표**: [../reviews/2026-07-02-codebase-review.md](../reviews/2026-07-02-codebase-review.md)의
R1–R18 **전 항목**을 Decision Record대로 구현/적용한다. 사용자가 전 항목을 사전 승인했으므로
이 사이클에 한해 **단계별 승인 게이트는 면제**된다(단, 각 Phase 완료를 audit.md에 기록).

**전제/규칙**
- 모든 작업 전 리뷰 문서와 이 계획을 읽는다. 이 계획이 스펙의 단일 출처(리뷰 문서는 근거).
- 테스트 우선 유지: 각 Phase 종료 시 `.venv/bin/python -m pytest tests/unit tests/pbt -q`
  전체 그린(시작 기준 271개, 순증 필수). 동작 변경엔 회귀 테스트를 추가/갱신한다.
  PBT(Hypothesis)가 커버하는 불변식을 깨는 변경은 PBT도 함께 갱신.
- Web UI 변경 Phase 후 Playwright e2e(`tests/e2e`, 데몬 불필요한 스모크 3종) 실행.
- 커밋: Phase 단위 1커밋, 한 줄 메시지, trailer 없음 (예: `U10 P1: fix status upstream, doctor tag, ...`).
- audit.md에 Phase마다 append (기존 포맷 유지, 절대 overwrite 금지).
- 완료 후 aidlc-state.md의 U10 섹션 갱신.
- 파괴적/외부 공개 작업 없음. 라이브 검증에 Docker/데몬이 필요하면 시도하되, 불가 환경이면
  "라이브 미검증" 항목으로 정직하게 기록하고 유닛/e2e로 대체.

**환경**: `.venv` 사용. hermes 0.17.0가 호스트(`~/.local/bin/hermes`)와 로컬 이미지
`nousresearch/hermes-agent:v2026.6.19`에 존재(스파이크에 활용 가능).

---

## Phase 1 — 정지(整地): dead code 제거 + 문구 수정 + 리팩토링 (R11, R12, R13)

기능 작업 전에 표면적을 줄인다. **주의**: R11 중 일부는 이후 Phase가 대체 구현하므로 아래 지시를 따를 것.

### R11 dead code
1. `wiring._detect_bridge_gateway` — 삭제하지 말고 **실구현으로 교체**(Phase 5 R14와 동일 작업을
   여기서 선행해도 됨): `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'`
   (subprocess, timeout 5s, 실패 시 None). advertise 우선순위: 설정값 > 감지값 > `172.17.0.1`.
2. `wiring.HERMES_DIR` 삭제 (R9가 새 상수를 도입).
3. `UpstreamClient.base_url` property 삭제.
4. `ChatService`의 `reuse_transport` 파라미터/`self._reuse` 분기/`_stream_oneshot` 삭제
   (pooled 경로만 유지). 관련 주석("legacy / remote") 정리.
5. `Transport._raw_stream`/`HermesApiTransport._raw_stream`의 `session_id` 인자 제거,
   `chat_stream(message)`로 시그니처 단순화. 호출부(chat.py)와 fakes/tests 동기화.
6. `agent rm --force` / `DELETE /agents/{name}?force` / `AgentService.remove(force=)` 제거
   (rm은 항상 강제 — 현행 동작 유지, 표면만 정직하게).
7. `gateway start`의 `--foreground/--no-foreground` 옵션 제거 (`-d/--daemon`만 유지;
   `start(foreground=not daemon, daemonize=daemon)`).
8. `pyproject.toml`에서 `pydantic>=2` 제거.
9. app.js `badge()` 첫 인자 제거.

### R12 문구/주석 (전부)
- `hermes_config.py` 모듈 docstring: api_key 인라인 기록 사실 반영.
- `provisioner.workspace_for` docstring: `/opt/data/workspace`.
- app.js chat 헤더 "ephemeral session" → 세션 영속 반영(예: 이름만 표시하거나 "persistent session").
- `chat._gate`: `rec.lifecycle == creating`이면 메시지를 "still provisioning — try again shortly"
  계열로 분기 (code는 동일 `agent_unavailable` 유지).
- `settings.ensure_configured` 에러문에서 "(U4 will add …)" 미래형 제거 —
  실제 안내: env 또는 `caduceus gateway config --upstream-url/--model`, 또는 `gateway start` 대화형.

### R13 리팩토링 (전부)
1. `_now()` 통합: `caduceus/common/util.py` 신설(`now_iso()`), 5개 모듈 교체.
2. progress-emit 어댑터 통합: util에 `call_maybe_async(fn, *args)` 또는 `make_emit(progress)`
   1개 — `agents/service.py`, `agents/images.py` 공용.
3. `daemon/wiring.Services` 필드에 실제 타입 부여(순환 임포트는 `TYPE_CHECKING`/문자열 어노테이션).
4. `GatewayStatus` 조립 단일화: wiring에 `build_status(services)` 하나를 두고 control_api
   `/status`와 `_dashboard_snapshot`이 공유 (R1이 이 함수에 upstream/uptime을 채움).
5. `asyncio.get_event_loop().time()` → `asyncio.get_running_loop().time()` (service.py 2곳).
6. `Settings.from_env()` → `return cls.from_env_and_file(path=None)` 위임으로 중복 제거.
7. control_api `POST /agents`: JSON 파싱/`CreateSpec.from_dict`를 try로 감싸 400 JSON 반환.

**검증**: 전체 스위트 그린. `grep`으로 제거 심볼 잔존 0건 확인.

---

## Phase 2 — P1 버그 수정 (R1–R8)

### R1 status upstream/uptime
- wiring `build_status()`에서: `upstream` = `_endpoint_reachable(settings.upstream_base_url)`
  결과를 `healthy|unhealthy`로 (TTL ~5s 인메모리 캐시 — 이벤트 스냅샷이 mutation마다 돌므로
  매번 TCP 다이얼 금지). `uptime_s` = 데몬 기동 시각(monotonic) 기준 — `Services`에
  `started_at` 주입(gateway `_serve`에서 세팅) 또는 build_services 시각 기록.
- Web UI 헤더는 이미 `status.upstream` 표시 중 — 값만 채워지면 됨. CLI `gateway status`는
  데몬이 떠 있으면 Control API `/status`를 조회하도록 변경(현재 state.json 직접 읽기 —
  살아있는 데몬의 실측값이 더 정확). 데몬 다운이면 현행 로컬 경로 유지.
- 테스트: status provider 유닛 + 캐시 TTL 동작.

### R2 doctor 이미지 태그
- `run_doctor(image_tag=...)` 기본값을 `caduceus.agents.images.DEFAULT_TAG`로.
  cli `doctor()`는 명시적으로 `image_tag=DEFAULT_TAG` 전달. 문구 "pulled automatically on
  first `caduceus agent create`". 테스트 갱신.

### R3 creating 좀비
- `AgentService.reconcile_all()`(부팅 전용)에서: `lifecycle == creating`인 로컬 레코드 →
  `failed` + `last_health.detail="daemon restarted mid-provision"` + 잔여 컨테이너가
  statuses에 있으면 `_safe_remove`. 런타임 reconcile(`_reconcile_lifecycle`)은 현행 유지.
- 주의: reconcile_all의 기존 "creating skip"은 부팅 시점에 in-flight job이 없음을 전제로
  제거되는 것 — 메서드 docstring에 "boot-time only" 계약 명시.
- 테스트: creating 레코드 + 컨테이너 유/무 2케이스.

### R4 CLI 스트림 타임아웃
- `ControlAPIClient.chat`/`logs`: `timeout=httpx.Timeout(30.0, read=None)` (connect/write/pool
  30 유지, read 무제한 — 서버측 hermes idle timeout 120s가 실질 가드).
- `cli/app.py` `_chat_once`/`agent logs`/기타 스트림 소비부: `httpx.HTTPError`를 잡아
  `render.error` + exit 1. (client 계층에서 감싸도 됨 — httpx 임포트가 이미 있는 client.py에서
  ControlError로 변환하는 편이 CLI를 깔끔하게 유지.)
- 테스트: 타임아웃 파라미터 전달 검증(주입 fake client) + 예외 변환.

### R5 create 옵션 실구현
- `AgentService.create(name, wait, progress, *, model=None, image=None)`:
  - `model` → `rec.model_alias` (없으면 서비스 기본 `default`). hermes config 렌더링은 이미
    `model_alias`를 사용하므로 자동 반영. AI-GW는 비-sentinel 모델을 upstream에 pass-through.
  - `image` → `ensure_image(image or self.image_tag)`.
- `CreateSpec`: `upstream_url` 필드 **제거**, `model`/`image` 유지. control_api가 두 값을
  service.create에 전달. CLI `--upstream-url` 제거, `--model/--image` help 문구 추가.
  Web UI 모달: Upstream URL 필드 제거, Model/Image 필드 유지(전송 payload 동기화).
- 테스트: model/image가 레코드/ensure_image 호출에 반영되는지; round-trip DTO 갱신.

### R6 register --auth 실구현
- `AgentRecord`에 `serve_auth: Optional[str] = None` 추가 (to_dict/from_dict + PBT round-trip
  갱신). **secret이므로 AgentView로 절대 투영 금지.**
- `HermesApiTransport._new_client`: bearer = `rec.serve_auth or rec.token`.
- `AgentService.register`: `auth`를 `serve_auth`에 저장. guidance 분기: `--auth` 제공 시
  "기존 API 키로 접속함, LLM 라우팅용 토큰은 아래" / 미제공 시 현행 문구.
- 테스트: serve_auth 우선순위, view 비노출, round-trip.

### R7 supervisor circuit 타이밍
- `_handle_local_unhealthy` 재구성: back-off 게이트 통과 후 **재시작 실행 전에**
  `if state.restart_attempts >= self.restart_threshold: → circuit open + mark_failed + return`.
  즉 N번의 재시작 기회를 모두 소진하고도 여전히 unhealthy로 N+1번째가 필요할 때 open.
  성공한 재시작은 다음 sweep의 healthy → `state.reset()`으로 자연 회복(현행 유지).
- 기존 유닛/PBT(stateful supervisor) 기대값 갱신 — 총 재시작 횟수 의미가 "시도 N회 후 open"
  으로 명확해짐.

### R8 registry 손상 내성
- `Registry.load()`: `json.JSONDecodeError`/`KeyError`/`ValueError` 시
  `state.json` → `state.json.corrupt-<UTC ts>` rename 백업, 빈 레지스트리로 시작,
  `log.warning` (백업 경로 포함). 테스트: 손상 파일 → 기동 성공 + 백업 생성.

**검증**: 전체 스위트 그린(신규 테스트 포함).

---

## Phase 3 — R9 `agent config` 실구현 (최대 항목)

### 3a. 스파이크 (구현 전 필수, 결과를 audit에 기록)
- hermes 0.17.0 config.yaml 스키마 확인: 호스트 hermes 설치본
  (`~/.local/bin/hermes`, `pip show`/site-packages의 config 로더 소스) 또는 이미지 내부
  (`docker run --rm --entrypoint cat nousresearch/hermes-agent:v2026.6.19 ...`)에서
  다음 매핑을 확정한다:
  - `soul` ↔ hermes의 persona/soul 키 (예: `soul:` 또는 `system_prompt:` — 실키 확인)
  - `skills` ↔ skills 목록 키
  - tools enable/disable ↔ toolset/tool 활성화 키 (우리가 이미 렌더링하는
    `platform_toolsets.api_server` 목록과의 관계 포함)
  - `core` ↔ 일반 top-level 키-값 (제한 목록 둘지 자유 키로 둘지 결정 — 기본: 자유 키,
    단 `model`/`api_key` 등 caduceus 소유 키는 **거부**)
- 매핑 불가한 필드가 있으면: 해당 필드를 ConfigSnapshot/ConfigChange에서 제거하는 것까지
  허용(공격적 리팩토링 승인됨). 결정을 이 파일 하단 "Spike Notes"에 추기.

### 3b. 구현
- `daemon/wiring.py`의 placeholder 3종을 실구현으로 교체:
  - `read_config(rec)`: `docker cp <cn>:/opt/data/config.yaml -` (provisioner에
    `read_file(container, path) -> str` 메서드 추가) → YAML 파싱(신규 의존성 금지 —
    stdlib에 YAML이 없으므로 **주의**: 우리가 쓰는 config는 우리가 렌더링한 단순 구조.
    선택지: (1) `pyyaml` 의존성 추가(가장 견고 — hermes 이미지가 아닌 caduceus 쪽 의존성이므로
    허용, pyproject에 추가) — **이걸 기본으로 한다**; (2) 자체 미니 파서(금지: 취약).
  - `write_config(rec, snapshot)`: 현행 caduceus-소유 키(model/approvals/platform_toolsets/
    tool_loop_guardrails/terminal.cwd)를 **보존**하면서 snapshot 필드를 병합 렌더 →
    `provisioner.write_config`(기존 docker cp 경로) 재사용.
  - `reload_agent(rec, strategy)`: hermes에 hot-reload 신호가 없으므로
    `CHANGE_KIND_STRATEGY` 전 항목을 `restart_serve`로 변경하고 컨테이너 재시작
    (`provisioner.stop→start` + host_port 갱신 — `AgentService.start`의 port-refresh 로직
    재사용을 위해 콜러블 주입 정리). ReloadStrategy seam은 유지(미래 hot-reload 대비).
- ConfigService/ConfigEditor 파이프라인(read→reduce→write→reload→read-back verify)은 설계
  그대로 살린다 — placeholder만 실체화.
- 제약: 재시작이 세션에 미치는 영향 확인(HERMES_HOME anon volume은 restart에 살아남음 —
  세션 유지됨). config 적용 후 health 재확인은 기존 editor 로직이 수행.
- 테스트: reducer/verify는 기존 테스트 유지; 신규 — YAML round-trip(caduceus-소유 키 보존),
  fake provisioner 기반 read/write/reload 통합, 원격 read-only 거부(기존).

---

## Phase 4 — 취소 + Web UI + 원격 히스토리 (R10, R15, R18)

### R10 chat cancel
- `ChatService.cancel(name)`: pooled entry가 있고 스트리밍 중이면 `transport.request_cancel()`
  (transport의 `_cancelled`/`_stop_run` 경로가 이미 구현됨 — done{cancelled} 터미널 보장).
- control_api: `POST /agents/{name}/chat/cancel` → 404(무명) / 200 `{cancelled: bool}`.
- CLI는 변경 없음(Ctrl-C 연결 종료로 충분 — SSE 끊김이 서버측 취소 유발).

### R18(a) Web UI Stop 버튼
- composer 옆 Stop 버튼: `state.streaming` 중에만 활성. 클릭 →
  `POST /agents/{sel}/chat/cancel`; 스트림은 done{cancelled}로 자연 종료.
- e2e: 스모크에 버튼 존재/비활성 기본 확인 추가(실 취소는 라이브 검증 항목).

### R18(b) minimal markdown
- 외부 라이브러리 없이 assistant 최종 답변에 한해: 코드펜스(```) → `<pre><code>`,
  인라인 코드, **bold**, 링크 텍스트, 리스트 정도의 보수적 변환. **XSS 금지**: 원문을
  escape 후 제한된 패턴만 태그 치환 (innerHTML에 raw 삽입 금지). 스트리밍 중에는 plain
  텍스트로 붙이고 done 시점에 1회 렌더(단순/견고).

### R18(c) health detail 툴팁
- `AgentView`에 `health_detail: str = ""` 추가(secret 없음 — `last_health.detail`).
  카드 badge에 `title=` 속성으로 노출. CLI `--json`에도 자연 포함.

### R15 원격 히스토리
- `ChatService.history` 가드: `rec is None or not rec.session_id → []`
  (kind 조건 제거). 원격은 세션이 만들어진 뒤(첫 chat 후)부터 replay 가능.
- 테스트: 원격 + session_id 有 → transport.load_history 호출됨.

**검증**: 전체 스위트 + Playwright e2e 그린.

---

## Phase 5 — 운영 편의 + 문서 (R14, R16, R17, README)

### R16 gateway stop 대기 + restart
- `GatewayService.stop(wait=True, timeout=10.0)`: SIGTERM 후 pid 소멸을 0.2s 간격 폴링,
  타임아웃 시 "still running (pid N)" 경고 반환. CLI `gateway stop` 메시지:
  "gateway stopped" / 타임아웃 경고.
- `gateway restart` 커맨드: stop(wait) → start(동일 플래그 `-d` 지원).

### R17 doctor upstream 체크
- 설정된 `upstream_base_url`에 TCP(또는 GET `/models` 200/404 무관 — 도달성만) 체크.
  미설정이면 required=True FAIL + 설정 안내. 도달 불가면 required=False warn(데몬 없이도
  네트워크가 다를 수 있음 — 아니, upstream은 호스트 기준이므로 **required=True**로 한다.
  단 미설정과 구분되는 메시지).

### R14 advertise 감지 + README
- Phase 1에서 구현한 bridge 실감지를 확인. README에 보안 모델 명시: AI-GW는 `0.0.0.0:9701`
  bind(원격 에이전트의 LAN 접근 필요), bearer 필수, 신뢰 네트워크 전제, 축소하려면
  `CADUCEUS_AIGATEWAY_BIND`로 bridge IP bind 가능.

### README/문서 동기화 (전 Phase 반영)
- 제거된 옵션(`--upstream-url`, `rm --force`, `--no-foreground`), 신규 기능(`--model/--image`,
  `register --auth`, `agent config` 실동작, `chat/cancel`, `gateway restart`, doctor 항목,
  Stop 버튼) 반영. aidlc-state.md U10 섹션 갱신.

---

## 완료 기준 (Definition of Done)
1. R1–R18 전 항목 구현 완료, Decision Record와 일치.
2. `pytest tests/unit tests/pbt` 전체 그린 (시작 271 → 순증; 삭제 기능의 테스트는 제거 OK).
3. Playwright e2e 그린.
4. 제거 대상 심볼 grep 잔존 0.
5. audit.md에 Phase별 기록, aidlc-state.md 갱신, README 동기화.
6. Phase별 커밋(한 줄 메시지) 완료. 가능하면 라이브 스모크(데몬 기동 → status에 upstream 표시
   → agent create --model → config --add-skill → chat → Stop) 수행 후 결과 기록;
   불가 시 "라이브 미검증" 명시.

## Spike Notes (Phase 3a에서 추기)
- (비어 있음)
