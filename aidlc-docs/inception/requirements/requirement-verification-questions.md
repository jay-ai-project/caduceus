# Caduceus — 요구사항 확인 질문 (Round 2: 게이트웨이/AI-프록시 허브)

> 이전 질문지는 확장된 요구사항으로 대체되었습니다. 각 질문의 `[Answer]:` 태그 뒤에 보기 문자(A/B/C, 또는 X로 직접 설명)를 채워 주세요.
> 빠르게 진행하려면 **(권장)** 표시 보기를 그대로 선택하셔도 됩니다. 작성 후 "완료"라고 알려주세요.

---

## 제가 확인한 핵심 사실 (설계 근거)

- **AI-게이트웨이(LLM 프록시) 패턴은 hermes가 기본 지원합니다.** 현재 호스트 `~/.hermes/config.yaml` 도 이미 `custom_providers` 로 `base_url: http://localhost:11434/v1`, `model: your-model` 를 사용 중입니다. 따라서 각 에이전트의 `base_url` 을 **caduceus 프록시**로 바꾸면, caduceus가 Ollama(기본) 또는 에이전트별 오버라이드로 포워딩할 수 있습니다. `hermes config set` 으로 프로그램적 설정도 가능합니다.
- **공통 전송(transport) 추상화가 가능합니다.** 원격 = `hermes serve`(JSON-RPC/WebSocket, 스트리밍 지원), 로컬 최적화 = `hermes acp`(stdio JSON-RPC, `sbx exec -i` 로 구동). 두 경로 모두 스트리밍 가능.
- **컨테이너 안의 `localhost` 는 호스트가 아닙니다.** 에이전트→caduceus 프록시는 `host.docker.internal:<port>` 로 접속해야 합니다. caduceus→Ollama 은 호스트에서 직접 `localhost:11434` 사용.
- **설정 편집**(skills/soul/tools)은 `hermes skills`/`hermes tools`/`hermes config set`/`SOUL.md` 로 가능하며, **로컬 sbx 에이전트는** `sbx exec`/`sbx cp` 로 확실히 편집 가능합니다. **원격 에이전트는** caduceus가 가진 접근 권한 수준에 따라 달라집니다(아래 Q5).

## 확정으로 가정한 사항 (이견 있으면 알려주세요)
- 에이전트 LLM 호출은 **기본적으로 caduceus 경유 + 기본 모델(`your-model`)**, 에이전트별 URL/모델 오버라이드는 **설계에는 포함하되 1차 구현 이후 단계**로.
- 세션 유지는 **에이전트당 단일 영속 세션 자동 이어가기** 기본.
- 로컬 프로비저닝은 **`sbx` + hermes 사전설치 이미지**(`shell` 에이전트 + 커스텀 템플릿).

---

## Question 1 — caduceus 토폴로지
caduceus를 어떤 구조로 만들까요? ("자체 gateway를 서비스" 한다는 요구를 어떻게 실체화할지)

A) **데몬 + 얇은 CLI 클라이언트 (권장)** — caduceus 데몬이 ①AI-게이트웨이(LLM 프록시) ②에이전트 대화 허브 ③레지스트리/상태를 상시 서비스하고, `caduceus` CLI는 데몬에 접속하는 클라이언트. 게이트웨이를 항상 서비스해야 하는 요구에 부합.

B) **CLI 단독** — 상시 데몬 없이 필요할 때만 프록시/연결 프로세스를 기동. 단순하지만 "상시 게이트웨이 서비스" 요구와는 거리가 있음.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — 전송(transport) 전략
로컬/원격 hermes에 연결하는 방식을 어떻게 가져갈까요? (스트리밍 등 공통 인터페이스는 양쪽 모두 필수)

A) **통합 우선 (serve-first) (권장)** — 로컬·원격 모두 `hermes serve`(JSON-RPC/WS) 단일 프로토콜로 연결(로컬 sbx는 포트 퍼블리시). 내부적으로 Transport 추상화는 두되 구현체는 우선 1개로 빠르게 일관성 확보. 로컬 ACP 최적화는 추후 추가.

B) **추상화 + 로컬 최적화 동시 (ACP now)** — 처음부터 Transport 추상화 + 두 구현체(로컬=ACP stdio, 원격=serve)를 함께 구현. 공통 스트리밍 인터페이스. 로컬 성능 이점은 크지만 초기 복잡도 상승.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — 구현 언어/스택
caduceus(데몬 + 프록시 + CLI) 구현 스택은?

A) **Python** (`typer` + `FastAPI` + `httpx`/`websockets`) — 비동기 프록시·SSE 스트리밍·WS 클라이언트·CLI 모두 용이, hermes와 동일 생태계 (권장)

B) **Go** (`cobra` + `net/http`) — `sbx` 와 동일 스택, 단일 바이너리 배포, 동시성 강점

C) **Node/TypeScript** — SSE/WebSocket 스트리밍 친화적, 단일 런타임

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — hermes 이미지 프로비저닝
로컬 sbx 샌드박스에 hermes를 "사전설치 이미지"로 올리는 방식은?

A) **Dockerfile 작성 (권장)** — hermes 설치 Dockerfile을 우리가 작성하고 caduceus가 빌드/태그하여 `sbx create shell -t <이미지>` 로 사용. 재현 가능·버전 관리 용이.

B) **스냅샷** — 수동 구성한 샌드박스를 `sbx template save` 로 템플릿화하여 재사용.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — 설정 편집(skills/soul/tools) 적용 범위
"에이전트 설정 편집" 요구의 1차 적용 범위는?

A) **로컬 우선 (권장)** — 로컬 sbx 에이전트는 `sbx exec`/`sbx cp` 로 skills/soul/tools/config 편집 전면 지원. 원격 에이전트는 1차에서는 읽기/조회 위주(또는 추후 지원).

B) **로컬 + 원격 모두** — 원격 hermes에 대한 셸/파일 접근 수단(SSH 등)을 전제로 원격 편집도 1차 포함. (※ 원격 접근 자격증명/경로 정보 필요)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6 — `caduceus` 명령 범위 (1차)
1차 구현에 포함할 명령 세트는?

A) **핵심** — `agent create`(로컬 sbx 프로비저닝), `agent register`(원격 등록), `agent ls`, `agent chat`, `agent rm`, `gateway`(데몬 start/stop/status)

B) **표준** — 핵심 + `agent stop/start`, `agent config`(skills/soul/tools 편집), `agent logs`

C) **확장** — 표준 + `agent exec`(샌드박스 임의 명령), `agent restart`(hermes 재기동), 에이전트별 LLM 오버라이드 `agent set-model/url`

X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

# 확장(Extension) 적용 여부

> 이번 확장으로 caduceus는 **네트워크에 노출되는 프록시/게이트웨이 + 원격 등록 + 자격증명**을 다루게 되어 보안·복원력 관련성이 높아졌습니다. 그 점을 감안해 선택해 주세요.

## Question 7 — Security 확장
보안(Security) 확장 규칙을 강제 적용할까요?

A) Yes — 모든 SECURITY 규칙을 차단성(blocking) 제약으로 적용 (네트워크 노출 프록시/게이트웨이가 포함되므로 권장)

B) No — SECURITY 규칙 생략 (PoC/프로토타입/실험용)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 8 — Resiliency 확장
복원력(Resiliency) 베이스라인을 적용할까요?

**이 확장이 하는 일:** 신뢰성/복원력 모범사례 기반의 **설계 시점 방향성 가이드**(내결함성·고가용성·관측가능성·복구가능성 등 15개 영역)를 요구사항·설계·코드에 반영.
**하지 않는 일:** 프로덕션 준비/가용성·RTO·RPO 보장 아님. 정식 신뢰성 검토의 대체가 아닌 **시작점**.

A) Yes — 복원력 베이스라인을 설계 가이드로 적용 (상시 데몬·다중 에이전트 연결이 있으므로 권장)

B) No — 생략 (빠른 반복 우선의 PoC/프로토타입)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 9 — Property-Based Testing 확장
속성 기반 테스트(PBT) 규칙을 적용할까요?

A) Yes — 모든 PBT 규칙을 차단성 제약으로 적용 (프록시 변환·직렬화·상태 관리 로직이 있어 적합)

B) Partial — 순수 함수와 직렬화 왕복(round-trip)에만 PBT 적용

C) No — PBT 규칙 생략 (단순 통합 계층 위주로 볼 경우)

X) Other (please describe after [Answer]: tag below)

[Answer]: A
