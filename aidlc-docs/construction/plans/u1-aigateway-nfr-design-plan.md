# U1 AI-Gateway — NFR Design Plan

**Unit**: U1 — AI-Gateway. **Stage**: NFR Design.

This plan (A) lists U1 NFR-design artifacts and (B) asks the **deferred project-wide Resiliency process questions** (RESILIENCY-03/04/14/15). Those four are cross-cutting (not U1-specific) and are asked **once** here at the first unit; the answers propagate to all units and to Build & Test. The resiliency rules require these to be **asked, not assumed**.

Fill `[Answer]:` in Part B, then say "완료". For a personal local tool, the **(권장)** options are sensible defaults.

---

## Part A — U1 NFR-design artifacts (after answers)
- [x] `construction/u1-aigateway/nfr-design/nfr-design-patterns.md` — resilience/perf/security patterns for U1 (timeout, cancellation, error-normalization, streaming pass-through, token-auth middleware, redaction)
- [x] `construction/u1-aigateway/nfr-design/logical-components.md` — U1 internal logical components (AuthMiddleware, RouteResolver, UpstreamClient w/ timeouts, StreamPump, ErrorMapper, ModelsAugmenter, MetricsCounter)

*(U1-specific NFR patterns are largely determined by the functional design + NFR requirements; they will be documented directly. No U1-specific pattern questions are open.)*

---

## Part B — Deferred Resiliency process questions (project-wide)

## Question 1 — 변경 관리 (RESILIENCY-03)
이 워크로드(개인 로컬 개발 도구)의 프로덕션 변경은 어떻게 통제할까요?

A) 기존 조직 변경관리 프로세스 사용 (이름/도구 명시)

B) 경량 변경관리 제안 (변경기록 + 승인 + 롤백 노트)

C) **N/A — 정식 변경관리 면제 (개인/내부 도구), 사유 문서화 (권장)**

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 2 — CI/CD · 롤백 · 배포 방식 (RESILIENCY-04)
> 참고: PBT 확장(PBT-08)이 **CI에서 속성테스트 실행(시드 로깅)** 을 요구하므로, 최소한의 CI는 사실상 필요합니다.

A) **권장 번들** — CI=**GitHub Actions**(pytest+Hypothesis, 시드 로깅), 롤백=**이전 버전 재설치**(버전 고정 pip/pipx), 배포=**직접 설치(in-place)**. 개인 도구에 적합 + PBT-08 충족.

B) 기존 파이프라인/절차 사용 (명시)

C) 커스터마이즈 — CI/롤백/배포를 따로 지정 (X에 기술)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — 복원력 테스트 방식 (RESILIENCY-14)
복원력 메커니즘(타임아웃/장애 시 우아한 성능저하/감독)을 어떻게 검증할까요?

A) **경량 결함주입 통합테스트 제안 (권장)** — upstream/agent 다운을 시뮬레이션해 graceful degradation 확인(AC-4와 정렬). Build & Test에 포함.

B) 기존 카오스/게임데이 관행 사용 (명시)

C) Operations 단계로 연기 (시나리오만 지금 기록)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — 인시던트 대응 (RESILIENCY-15)
프로덕션(여기서는 로컬 데몬) 문제 발생 시 대응은?

A) 기존 인시던트 대응 프로세스 사용 (명시)

B) **경량 제안 (권장)** — 로그 기반 트러블슈팅/triage 노트 + 간단한 복구 절차(데몬/에이전트 재기동). 정식 온콜 없음.

X) Other (please describe after [Answer]: tag below)

[Answer]: B
