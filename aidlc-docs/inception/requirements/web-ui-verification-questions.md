# Requirements Verification — Gateway Web UI (candidate Unit U5)

> 답변은 각 질문의 `[Answer]:` 태그 뒤에 영문 letter(A/B/C/...)로 적어주세요.
> 제시된 보기가 맞지 않으면 **E) Other** 를 고르고 `[Answer]:` 뒤에 직접 설명해 주세요.
> 여러 질문에 한 번에 답해도 됩니다.

## 요청 요약 (제가 이해한 내용)
`caduceus gateway` 실행 시 간단한 Web UI 를 제공한다.
- **Dashboard**: 생성된 agent 목록 + 연결 상태 + 샌드박스 프로비저닝 상태 + 연결 정보
- **신규 agent 추가**: 로컬 sandbox 생성(프로비저닝) / remote 등록, 실시간 상태 표시
- **채팅**: 각 agent 와 대화창 진입, streaming chat, **thinking** 표시, **tool 호출 여부/결과** 표시
- 세션 기록 영속화는 불필요(휘발 OK). 단, 가능하면 sandbox 내 hermes agent 세션 기록을 불러오면 더 좋음(우선 local sbx 대상; remote 는 추후).

## 현재 코드베이스에서 확인한 사실 (참고)
- Control API 는 이미 loopback(`127.0.0.1:9700`)에 떠 있고, Web UI 가 필요한 기능 대부분의 엔드포인트를 이미 보유: `GET /status`, `GET /agents`, `POST /agents`(프로비저닝 **SSE 진행상황**), `POST /agents/register`, `DELETE /agents/{name}`, `POST /agents/{name}/stop|start`, `POST /agents/{name}/chat`(**SSE 스트리밍**), `GET /agents/{name}/config`, `GET /agents/{name}/logs`(SSE).
- AI-Gateway 는 별도 listener(`0.0.0.0:9701`).
- **중요**: 채팅 이벤트 모델(`ChatEvent`)은 현재 `token/message/error/done` 4종뿐이며, `transport/acp.py` 는 hermes 의 **thinking(thoughts) / tool 호출(tool_call) 알림을 버리고** `agent_message_chunk`(출력 텍스트)만 전달함. → UI 에서 thinking/tool 을 보여주려면 이벤트 모델 + ACP transport 확장이 필요(이 Unit 의 핵심 백엔드 작업).
- ACP `session/load` 는 기존 세션을 resume 하며 과거 대화를 `session/update` 로 **replay** 함 → 세션 기록 불러오기를 이 경로로 구현 가능.

---

## Q1. 프론트엔드 방식
A) **자체 포함 정적 SPA (vanilla HTML/JS/CSS), 빌드 단계 없음**, 데몬이 그대로 서빙 — Node 툴체인 불필요, "간단한 web ui"에 가장 부합 *(추천)*
B) 경량 프레임워크 + 빌드 단계 (React/Vite 또는 Vue) — 더 풍부하지만 Node 빌드 의존성 추가
C) 서버 렌더링 템플릿 (Jinja2 + htmx)
E) Other

[Answer]: A

## Q2. Web UI 서빙 위치 / 포트
A) **기존 Control API loopback listener(`127.0.0.1:9700`)에 마운트** — 기존 엔드포인트 재사용, UI 는 예: `http://127.0.0.1:9700/` *(추천)*
B) 전용 UI listener 를 별도 포트로 추가 (loopback, 설정 가능)
E) Other

[Answer]: A

## Q3. thinking / tool 호출 표시 깊이 (이벤트 모델 + ACP transport 확장 필요)
A) **풀(full)**: thinking 텍스트 스트리밍 + tool 이름 + 인자(args) + 결과(result) 를 접을 수 있는(collapsible) 영역으로 인라인 표시 *(추천)*
B) 인디케이터만: "thinking…" 표시 + "tool: X 호출됨" 배지 정도 (args/result 상세는 생략)
C) 텍스트 토큰만 (thinking/tool 미표시, 현재 동작 유지)
E) Other

[Answer]: A

## Q4. UI 에서의 agent 추가 범위
A) **CLI `agent create` 와 동등(로컬 sandbox 프로비저닝, 실시간 SSE 진행상황) + remote register 도 지원** *(추천)*
B) 로컬 sandbox 생성만 (remote 등록은 UI 에서 제외, 추후)
E) Other

[Answer]: A

## Q5. 채팅 세션 기록 불러오기 (local sbx hermes)
A) **대화창 진입 시 agent 의 persist 된 세션을 resume 하고, ACP `session/load` replay 를 캡처해 과거 turn 들을 렌더링** (best-effort; 미지원/실패 시 빈 화면) *(추천)*
B) 기록 불러오기 없음 — 대화창은 항상 빈 상태로 시작 (서버측 세션 연속성은 유지)
E) Other

[Answer]: A

## Q6. Web UI 접근 보안/노출
A) **loopback 전용, 인증 없음** (개인 로컬 도구, Control API 와 동일 노출 수준) *(추천)*
B) 간단한 토큰/패스워드 게이트 추가
E) Other

[Answer]: A

## Q7. Dashboard 실시간성
A) **주기적 polling** (예: 수 초마다 agent 목록/상태 갱신) — 가장 단순 *(추천)*
B) SSE/WebSocket 으로 상태 변경 push (서버 측 추가 작업 필요)
E) Other

[Answer]: A

## Q8. 이 Unit 의 Extension 설정 (현재 프로젝트 레벨: Security=No, Resiliency=Yes/full, Property-Based Testing=Yes/full)
A) **프로젝트 설정 그대로 상속** *(추천)*
B) 이 Web UI(신규 네트워크-facing 표면)에 한해 Security Baseline 도 활성화
C) 이 UI Unit 은 대부분 프론트엔드 glue 이므로 PBT 를 "light" 로 완화
E) Other

[Answer]: A

## Q9. 추가로 원하시는 점 / 제약 (자유 기술, 선택)
예: 다크모드, 특정 레이아웃, agent config 편집 UI 포함 여부, logs 보기 포함 여부 등.

[Answer]: 
