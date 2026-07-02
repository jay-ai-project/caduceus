# Codebase Review — 2026-07-02

전체 소스(`caduceus/` ~5,700줄, U1–U9 완료 시점, 271 unit+PBT 통과 상태) 정독 결과입니다.
각 항목의 `[Answer]:` 에 **A**(제안대로 적용) / **B**(수정해서 적용 — 코멘트) / **C**(스킵) 로 답해 주세요.

> **✅ DECIDED 2026-07-02 — 전 항목 승인.** 사용자 결정: "모든 제안을 가장 견고한 수준으로
> (미구현 항목은 구현, 추천 제안은 수락) 다 승인. 큰 규모 변경/공격적 리팩토링 허용."
> 개별 답은 문서 말미의 **Decision Record** 참조. 실행 스펙은
> [../plans/2026-07-02-review-remediation-plan.md](../plans/2026-07-02-review-remediation-plan.md).

**총평(아키텍처)**: ports & adapters + 주입 기반 합성(composition root)이 일관되게 지켜져
있고, 유닛 경계(U1 게이트웨이 / U2 레지스트리·프로비저너 / U3 트랜스포트 / U4 데몬·CLI)가
명확합니다. **전면 재설계가 필요한 부분은 없습니다.** 다만 U7→U8 전환(ACP→HTTP/SSE) 과정에서
남은 죽은 코드/죽은 옵션, 그리고 "설계는 됐지만 구현이 비어 있는" agent config 기능이
가장 큰 정리 대상입니다.

---

## 🔴 P1 — 버그 / 잘못된 동작 (사용자가 실제로 겪는 것)

### R1. `gateway status` / Web UI 헤더의 upstream이 항상 "unknown"
- `GatewayStatus.upstream`을 채우는 코드가 어디에도 없음 → CLI `gateway status`와
  Web UI 헤더가 영구히 `upstream unknown` 표시.
  ([dto.py:96](caduceus/common/dto.py#L96), [control_api.py:65-75](caduceus/daemon/control_api.py#L65-L75), [wiring.py:140-151](caduceus/daemon/wiring.py#L140-L151))
- `uptime_s`/`_started_at`도 선언만 되고 미사용(같은 계열).
- **제안**: `/status` 및 `_dashboard_snapshot`에서 upstream TCP reachability
  (`_endpoint_reachable`, 이미 존재)를 짧은 캐시(예: 5s)와 함께 채우고, `uptime_s`도 채움.
- [Answer]:

### R2. `caduceus doctor`가 항상 "hermes image not built yet" 경고
- `run_doctor(image_tag="caduceus/hermes:0.17.0")` 기본값이 U8 이전의 **폐기된 태그**.
  실제 이미지는 `nousresearch/hermes-agent:v2026.6.19`(`images.DEFAULT_TAG`)이고,
  CLI는 image_tag를 넘기지 않음 → 이미지가 있어도 항상 경고 + "Built automatically" 문구도
  이제 build가 아니라 pull이라 부정확. ([doctor.py:70](caduceus/config/doctor.py#L70), [cli/app.py:314](caduceus/cli/app.py#L314))
- **제안**: 기본값을 `images.DEFAULT_TAG`로 교체(단일 출처), 문구 "pulled automatically"로 수정.
- [Answer]:

### R3. 데몬이 프로비저닝 중 죽으면 `creating` 좀비 레코드가 영구 잔류
- `reconcile_all()`과 `list()`의 reconcile 모두 `lifecycle == creating`을 건너뜀
  (진행 중인 job 보호 목적). 그러나 **데몬 재시작 직후에는 in-flight job이 존재할 수 없으므로**,
  크래시로 남은 `creating` 레코드는 영원히 `creating`으로 표시되고 `agent rm` 외엔 복구 불가,
  같은 이름 재생성도 "already exists"로 막힘.
  ([service.py:285](caduceus/agents/service.py#L285), [service.py:305](caduceus/agents/service.py#L305))
- **제안**: 부팅 reconcile에서만 `creating` → `failed`(detail: "daemon restarted mid-provision")
  로 전이(+ 잔여 컨테이너는 statuses 기준 정리). 런타임 reconcile은 현행 유지.
- [Answer]:

### R4. CLI 스트림(chat / logs -f)이 30초 무입력이면 traceback으로 사망
- `ControlAPIClient` 기본 `timeout=30.0`이 스트리밍 read timeout에도 적용됨.
  긴 tool 실행 등으로 이벤트가 30초 이상 없거나, 조용한 컨테이너에 `logs -f`를 걸면
  `httpx.ReadTimeout`이 발생 — `_chat_once`/`agent logs`는 `ControlError`만 잡으므로
  사용자에게 raw traceback이 노출됨. ([client.py:35](caduceus/cli/client.py#L35), [client.py:117-133](caduceus/cli/client.py#L117-L133))
- **제안**: `chat`/`logs` 호출에 `timeout=httpx.Timeout(30, read=None)` 지정 +
  CLI 레벨에서 `httpx.HTTPError`를 `ControlError`로 감싸 exit code 1 처리.
- [Answer]:

### R5. `agent create`의 `--model/--upstream-url/--image` 및 Web UI 폼 필드가 조용히 무시됨
- CLI와 Web UI 모달이 값을 받아 `CreateSpec`으로 보내지만 서버는 `spec.name`만 사용
  ([control_api.py:105,119](caduceus/daemon/control_api.py#L105), [service.py:80](caduceus/agents/service.py#L80)).
  사용자는 설정했다고 믿지만 아무 효과 없음.
- **제안 (택1)**:
  - **(a)** `--model` → `rec.model_alias`(hermes config에 이미 렌더링됨; 게이트웨이는
    비-sentinel 모델을 pass-through 하므로 그대로 동작), `--image` → per-create image tag로
    실제 구현. `--upstream-url`은 v2 라우팅 seam 전까지 **제거**.
  - **(b)** 세 옵션과 폼 필드 전부 제거(최소 변경, 정직한 UI).
- [Answer]:

### R6. `agent register --auth`가 조용히 버려짐
- `AgentService.register(name, endpoint, auth)`의 `auth`는 저장도 사용도 안 됨
  ([service.py:217](caduceus/agents/service.py#L217)). 현 설계(단일 자격증명: 민팅된 토큰 =
  AI-GW bearer = 원격 API_SERVER_KEY)에서는 원격 hermes가 caduceus 토큰을 자기 키로
  설정해야만 통신 가능 — `--auth`로 기존 키를 주면 될 거라 기대한 사용자는 인증 실패.
- **제안 (택1)**:
  - **(a)** `--auth` 제공 시 이를 **트랜스포트 bearer**로 사용하도록 `AgentRecord`에
    `serve_auth`(별도 필드) 복원 — 원격 등록이 훨씬 자연스러워짐.
  - **(b)** `--auth` 옵션 제거 + guidance 문구만 유지(최소 변경).
- [Answer]:

### R7. Supervisor가 3번째 재시작이 "성공해도" 즉시 circuit open + failed 마킹
- `restart_attempts >= restart_threshold`를 재시작 **시도 직후** 평가하므로, 3번째 재시작이
  성공했더라도 다음 sweep에서 healthy를 확인할 기회 없이 `failed`로 영구 마킹
  ([supervisor.py:163-174](caduceus/transport/supervisor.py#L163-L174)).
  이후 `agent ls`의 reconcile이 running으로 되돌려 상태가 왔다갔다 하는 불일치도 발생.
- **제안**: circuit open 판정을 "재시작을 **더 하려는 시점**에 이미 threshold 초과"로 이동
  (즉 3회 시도 후 여전히 unhealthy로 4번째가 필요할 때 open). BR-S5 의도("3 restart-fails")와 일치.
- [Answer]:

### R8. `state.json` 손상 시 데몬이 기동 불가 (raw traceback)
- `Registry.load()`가 `json.loads` 예외를 그대로 전파 ([registry.py:49-56](caduceus/agents/registry.py#L49-L56)).
  파일이 깨지면(디스크 풀 등) `gateway start` 자체가 죽음.
- **제안**: 손상 감지 시 `state.json.corrupt-<ts>`로 백업 후 빈 레지스트리로 기동 + 경고 로그.
  (에이전트 컨테이너는 살아 있으므로 부팅 reconcile이 일부 복구… 는 불가 — 레코드가 없으면
  reconcile 대상이 아님. 그래도 기동 불가보다는 낫다는 판단. 대안: 명확한 에러 메시지로 fail-fast)
- [Answer]:

---

## 🟠 P2 — 반쪽 기능 (설계만 있고 구현이 빈 것)

### R9. `agent config` (get/set) 전체가 placeholder — 실동작 없음
- `_make_read_config`/`_make_write_config`가 빈 `ConfigSnapshot()` 반환/no-op
  ([wiring.py:216-238](caduceus/daemon/wiring.py#L216-L238)). `agent config --get`은 항상 빈 값,
  `--add-skill` 등은 아무것도 안 쓰고 "NOT verified"로 끝남. U4에서 "Build & Test에서 확정"
  예정이었으나 U8 스토리지 개편을 거치며 미구현으로 남음. `HERMES_DIR = "/root/.hermes"`도
  이 잔재(미사용).
- **제안 (택1)**:
  - **(a)** 지금 구현: `docker cp`로 컨테이너의 `/opt/data/config.yaml`을 읽고/병합/쓰고
    컨테이너 재시작(restart_serve) — soul/skills는 hermes 스키마 확인 필요(스파이크 1회).
  - **(b)** 커맨드와 스텁 전부 제거하고 "미지원" 문서화 — 코드가 정직해짐. 필요 시 새 사이클로.
  - **(c)** 현행 유지하되 CLI에서 "not yet implemented" 에러를 명시적으로 반환.
- [Answer]:

### R10. 취소(cancel) 경로가 프로덕션에서 도달 불가 — Chat Stop 버튼 부재와 동일 사안
- `Transport.request_cancel()` / `_stop_run()`(Runs API stop)은 구현돼 있으나 이를 호출하는
  API/UI가 없음 ([base.py:74](caduceus/transport/base.py#L74), [hermes_api.py:269](caduceus/transport/hermes_api.py#L269)).
  현재 취소 수단은 SSE 연결 끊기(브라우저 새로고침)뿐.
- **제안**: Web UI 스트리밍 중 **Stop 버튼** + `POST /agents/{name}/chat/cancel` 라우트로
  pooled transport의 `request_cancel()`을 wiring (CLI는 Ctrl-C → 연결 종료로 이미 충분).
  스킵을 택하면 dead code로 두는 대신 주석으로 "미배선" 명시.
- [Answer]:

---

## 🟡 P3 — Dead code / 잘못된 주석·문서 (일괄 정리 제안)

### R11. dead code 일괄 제거
| 항목 | 위치 | 비고 |
|---|---|---|
| `_detect_bridge_gateway()` | [wiring.py:241-251](caduceus/daemon/wiring.py#L241-L251) | 두 분기 모두 `None` 반환 — 사실상 상수. 삭제하고 fallback `172.17.0.1` 유지(또는 `docker network inspect bridge`로 실구현) |
| `HERMES_DIR` | [wiring.py:213](caduceus/daemon/wiring.py#L213) | 미사용 (R9와 연동) |
| `UpstreamClient.base_url` property | [upstream.py:21-23](caduceus/aigateway/upstream.py#L21-L23) | 미사용 |
| `ChatService reuse_transport=False` + `_stream_oneshot` | [chat.py:46,123](caduceus/transport/chat.py#L123) | 어떤 코드/테스트도 `False`를 쓰지 않음 — 플래그와 oneshot 경로 삭제 |
| `Transport._raw_stream(session_id, ...)`의 `session_id` 인자 | [base.py:67](caduceus/transport/base.py#L67), [hermes_api.py:186](caduceus/transport/hermes_api.py#L186) | 구현이 `self.session_id`만 사용 — 시그니처에서 제거 |
| `agent rm --force` / DELETE `force` | [cli/app.py:109](caduceus/cli/app.py#L109), [service.py:316](caduceus/agents/service.py#L316) | 서비스가 무시(항상 강제 rm) — 옵션 제거 또는 의미 부여 |
| `gateway start --foreground/--no-foreground` | [cli/app.py:224](caduceus/cli/app.py#L224) | `-d` 없이 `--no-foreground`는 무의미 — 옵션 제거(`-d`만 유지) |
| `pyproject.toml`의 `pydantic>=2` 직접 의존 | pyproject.toml | 코드 어디서도 직접 import 안 함(FastAPI가 견인) — 제거 |
| app.js `badge(cls, value)`의 첫 인자 | [app.js:89](caduceus/webui/assets/app.js#L89) | 미사용 인자 |
- [Answer]:

### R12. 오해를 부르는 주석/문구 일괄 수정
| 항목 | 위치 | 문제 |
|---|---|---|
| `hermes_config.py` 모듈 docstring | [hermes_config.py:4-5](caduceus/agents/hermes_config.py#L4-L5) | "토큰은 env로만 전달, 렌더된 텍스트에 secret 없음" — 실제로는 `api_key` 인라인 기록(#28660 대응)과 모순 |
| `workspace_for` docstring | [provisioner.py:109](caduceus/agents/provisioner.py#L109) | "bind-mounted at /workspace" — 실제는 `/opt/data/workspace` |
| Web UI chat 헤더 "ephemeral session" | [app.js:222](caduceus/webui/assets/app.js#L222) | 세션은 영속(session_id 저장 + history replay) — 문구 삭제/변경 |
| `_gate`의 creating 안내문 | [chat.py:205-208](caduceus/transport/chat.py#L205-L208) | 프로비저닝 중인데 "recover with `agent start`" 안내 — creating이면 "still provisioning, try again shortly"로 분기 |
| `settings.py` `ensure_configured` 에러문 | [settings.py:156-158](caduceus/common/settings.py#L156-L158) | "(U4 will add an interactive setup…)" — 이미 구현된 기능을 미래형으로 안내 |
- [Answer]:

---

## 🔵 P4 — 리팩토링 (동작 불변, 유지보수성)

### R13. 소소한 구조 정리 일괄
1. `_now()`가 5개 모듈에 중복 — `caduceus/common/util.py`(또는 models.py)로 통합.
2. progress-emit 어댑터(`_emit`, sync/async 판별)가 `service.py`/`images.py`에 중복 — 헬퍼 1개로.
3. `Services` dataclass 필드 6개가 `"object"` 타입 — 실제 타입(문자열 어노테이션) 부여.
4. `GatewayStatus` 조립이 control_api `/status`와 wiring `_dashboard_snapshot`에 중복 —
   status builder 하나로 (R1과 함께 처리하는 게 자연스러움).
5. `asyncio.get_event_loop().time()` → `asyncio.get_running_loop().time()`
   ([service.py:182,190](caduceus/agents/service.py#L182)) — deprecated 패턴.
6. `Settings.from_env()`는 프로덕션 미사용(테스트만) — `from_env_and_file(path=None)`로 위임해
   중복 로직 제거.
7. control_api `POST /agents`에서 `CreateSpec.from_dict(await request.json())`이 try 밖 —
   깨진 JSON이 500 traceback → 400 JSON으로.
- [Answer]:

### R14. (advisory) AI-Gateway 기본 바인드 `0.0.0.0:9701`
- Infra 설계(U1)는 "docker bridge IP에 바인드"였으나 기본값은 all-interfaces
  ([settings.py:48](caduceus/common/settings.py#L48)) — bearer 인증만으로 LAN에 노출.
  개인 도구 + Security Baseline 미채택이므로 **advisory**: 기본값을 `172.17.0.1:9701`로
  바꾸거나 README에 노출 사실 명시. (WSL2 환경에선 실질 위험 낮음)
- [Answer]:

---

## 💡 P5 — 기능/사용성 제안 (선택)

### R15. 원격 에이전트 히스토리 허용
- U8에서 트랜스포트가 통합됐으므로 `ChatService.history()`의 local-only 가드는 ACP 시절
  잔재 ([chat.py:111](caduceus/transport/chat.py#L111)). 원격도 `session_id`만 있으면
  `GET /api/sessions/{id}/messages` replay 가능 — 가드를 `session_id` 유무로만 완화.
- [Answer]:

### R16. `gateway stop` 종료 대기 + `gateway restart`
- 현재 stop은 SIGTERM 송신 후 즉시 반환("signalled") — 이어서 `gateway start` 하면 lock
  경합 가능. stop에 종료 폴링(최대 ~10s) 추가, `restart` 커맨드 신설.
- [Answer]:

### R17. doctor에 upstream LLM 도달성 체크 추가
- 현재 doctor는 Docker/이미지/런타임/데몬만 확인. `upstream_base_url` TCP/HTTP 체크 1줄이면
  "왜 chat이 안 되지"의 최다 원인을 조기 진단.
- [Answer]:

### R18. Web UI 개선 소묶음
- (a) 스트리밍 중 Stop 버튼 — R10과 동일 작업.
- (b) assistant 답변 markdown 렌더(외부 라이브러리 없이 minimal — 혹은 스킵).
- (c) `creating`/`failed` 에이전트 카드에 `last_health.detail` 툴팁 노출(현재 detail은 CLI
  `--json`으로만 확인 가능).
- [Answer]:

---

## 참고 — 검토했지만 "문제 아님"으로 판단한 것들
- `normalize_stream` 터미널 불변식, EventBus coalescing, Registry 원자적 저장, 헤더
  새니타이즈, 토큰 redaction, saga 보상 로직: 모두 견고. PBT 커버리지 적절.
- `AgentService.list()`가 레지스트리 레코드를 in-place로 변경하지만 미영속 — 의도된
  "라이브 프로젝션" 설계로 판단(부팅 reconcile이 영속화 담당). 변경 불요.
- 이중 uvicorn 서버의 시그널 처리 — 이론상 마지막 서버가 핸들러를 덮어쓰는 우려가 있으나
  U6 Build & Test에서 clean shutdown 라이브 검증됨. 관찰만.
- `token_lookup`의 타이밍 비교(constant-time 아님) — loopback 개인 도구라 위협 모델 밖.

---

## Decision Record (2026-07-02, 사용자 승인)

| 항목 | 답 | 세부 결정 |
|---|---|---|
| R1 | **A** | `/status` + `_dashboard_snapshot`에 upstream reachability(짧은 캐시) + `uptime_s` 채움 |
| R2 | **A** | `images.DEFAULT_TAG` 단일 출처, 문구 "pulled automatically" |
| R3 | **A** | 부팅 reconcile에서 `creating` → `failed` (detail: daemon restarted mid-provision) |
| R4 | **A** | chat/logs 스트림 read timeout 해제 + httpx 예외 → ControlError |
| R5 | **A-(a)** | `--model`→`model_alias`, `--image`→per-create image tag **구현**; `--upstream-url` 제거(CLI+WebUI+CreateSpec) |
| R6 | **A-(a)** | `AgentRecord.serve_auth` 도입 — `--auth` 제공 시 원격 트랜스포트 bearer로 사용 |
| R7 | **A** | circuit open 판정을 "추가 재시작이 필요한 시점에 threshold 초과"로 이동 |
| R8 | **A** | 손상 state.json → `.corrupt-<ts>` 백업 후 빈 레지스트리 기동 + 경고 |
| R9 | **A-(a)** | agent config **실구현** (docker cp 기반 /opt/data/config.yaml read-merge-write + 재시작; hermes 스키마 스파이크 선행) |
| R10 | **A** | `POST /agents/{name}/chat/cancel` + Web UI Stop 버튼 배선 |
| R11 | **A** | dead code 전 항목 제거 (bridge 감지는 **실구현**으로 대체 — R14 참조) |
| R12 | **A** | 문구/주석 5건 전부 수정 |
| R13 | **A** | 리팩토링 7건 전부 적용 |
| R14 | **A(수정)** | bind는 `0.0.0.0` 유지(원격 에이전트가 LAN에서 AI-GW에 접근해야 하므로 필요); advertise host의 bridge IP **실감지**(`docker network inspect bridge`) 구현 + README에 노출/인증 모델 명시 |
| R15 | **A** | history 가드를 `session_id` 유무로 완화 (원격 허용) |
| R16 | **A** | `gateway stop` 종료 대기(~10s 폴링) + `gateway restart` 신설 |
| R17 | **A** | doctor에 upstream 도달성 체크 추가 |
| R18 | **A** | (a) Stop 버튼(=R10), (b) 무의존 minimal markdown 렌더, (c) health detail 툴팁 전부 적용 |
