# 데모 검증 기록 — 2026-09-19

> 아래 `runs/` 경로는 작성자의 로컬 검증 기록 식별자입니다. 원시 실행 로그는 공개 저장소에 포함하지 않았습니다. 새 실행은 자체 기록을 생성하며 아래 결과와 별도로 판단해야 합니다.

**로컬 웹 구현 완료. 크레딧 충전 후 실제 OpenAI + 로컬 Node의 전체 loop가 완료됐습니다. Daytona + OpenAI 실행은 비단조 관찰로 INCONCLUSIVE 종료했으며, 모든 생성 sandbox의 삭제를 확인했습니다.**

## 웹 구현 후 최신 검증

### 최종 UI·입력 계약 확인

- Python 자동 테스트 **36개 통과**. 웹 기본 실행의 Daytona + LLM 고정, Local/RULES 거부, 미지원 링크 차단, 데모 링크 정규화, 제거된 선택 메뉴·Demo Run 버튼 부재를 포함합니다.
- JavaScript 발표 로직 테스트 통과. 실제 관찰의 단일 조건 비교, 결정 이전의 증거만 사용, raw observation과 world spec 연결을 확인했습니다.
- 브라우저에서 이슈 입력의 Enter·클릭 제출, 미지원 링크 안내, 데모 링크 복원, JS 오류 없음을 확인했습니다. HTTP smoke의 기본 모드도 통과했고 이 확인 과정의 **유료 실행은 0회**입니다.
- Demo Run 열기·고정 기능은 최종 UI에서 제거했습니다. 기존 기록을 선택하고 발표 모드로 보는 흐름을 사용합니다.

### 발표 모드·다크 테마 후 짧은 확인

- 2026-09-19: `runs/20260919-151455-7921cd`, 실제 Daytona + OpenAI **6 worlds / 2 batches / LLM 1회 / 32.253초**. good/bad 재현 및 LLM이 고른 allocation/length/width 비교 실행을 확인했습니다. 생성 6개, 삭제 6개입니다.
- 요청에 따라 `--max-rounds 1 --max-worlds 6 --seconds 90`으로 제한했습니다. 한 라운드 이후 **INCONCLUSIVE (round budget)**로 종료했으며, 전체 경계 검증이나 Demo Run 성공 기록이 아닙니다. 추가 유료 재시도는 하지 않았습니다.
- Python 테스트 31개와 `tests/test_presentation.js`의 증거 순서·단일 조건 비교·모드 구분·Demo Run 자격 검증을 통과했습니다. 브라우저에서 다크 테마, 발표 장면 전환, 실제 기록의 lifecycle 및 cleanup 표시를 확인했습니다.

| 검증 | 결과 |
|---|---|
| 자동 테스트 | 31개 통과; lifecycle/취소/동시 시작/입력 검증 포함 |
| 실제 OpenAI + 로컬 Node | 55 worlds / 16 batches / LLM 6회 / 108.025초, VERIFIED_FAILURE_CONDITION 및 LLM STOP |
| 확인 조건 | Node 26.8.1 / pooled / implicit / Uint32, size 32,767 FAIL / 32,768 PASS, 각각 새 실행 5회 |
| 실제 OpenAI + Daytona | 12 worlds / LLM 4회 / 113.869초, 비단조 관찰에 INCONCLUSIVE; TTL 확인 12개, 삭제 12개 |
| 웹 안전 중단 | Daytona 생성 도중 중단 → CANCELLED, 생성된 2개 모두 삭제 |
| HTTP 검사 | 비밀 파일 접근 차단, 잘못된 Host/외부 Origin/토큰 없는 실행 차단, 중복 시작 거부, 증거 다운로드 성공 |
| 브라우저 검사 | 실제 화면·실행 기록·새로고침 확인, JS 오류 없음 |

- LLM 전체 loop: `runs/20260919-144400-5b5cea/summary.json`, 같은 폴더의 `events.jsonl` 및 planner 요청/응답. 실행은 Windows 로컬 프로세스이며 Daytona 결과와 구분해야 합니다.
- Daytona + LLM: `runs/20260919-143729-4f6e97/summary.json`. 큰 입력에서 PASS 이후 FAIL이 다시 관찰되어 확정하지 않았습니다. 이후 일반적인 단조 탐색 제약을 planner에 설명했으며 알려진 정답은 넣지 않았습니다.
- 웹 중단 검사: `runs/20260919-144236-e97b7c/summary.json`.
- 유료 호출 없는 자동 테스트: `.venv\Scripts\python -m unittest discover -s tests -v`.

측정 시간은 단일 실행 관찰입니다. 모델 선택은 매번 달라질 수 있으며 항상 경계 확정을 보장하지 않습니다. 웹 서버를 켜는 것만으로 실험을 시작하지 않습니다.

## 웹 구현 전 기록 — 크레딧 충전 이전

| 검증 | 결과 |
|---|---|
| 자동 테스트 | 22개 통과, 생성 API 계약 검증은 mock 사용 |
| 전용 가상환경 | Python 3.13.5 / requests 2.32.5 설치 및 테스트 통과 |
| 실제 Daytona + 규칙 기반 planner | 53 sandbox worlds / 15 batches / 118.675초 |
| 관찰 및 정리 | 53개 모두 유효한 observation, 53개 모두 `deleted=true` |
| 경계 반복 검증 | 32,767 bytes FAIL / 32,768 bytes PASS, 각각 새 sandbox 5회 |
| 고정 조건 | Node 26.8.1 / pooled / implicit / Uint32 |
| 실제 Windows 로컬 + 규칙 기반 planner | 53 process worlds / 15 batches / 1.448초 |
| 실제 OpenAI 모델 접근 확인 | HTTP 200 — 생성 성공이나 잔액을 뜻하지 않음 |
| 실제 OpenAI 생성 요청 | HTTP 429 / `credit_balance_exhausted` / `insufficient_quota` |

시간은 이번 단일 실행 관찰이며 성능 보장이 아닙니다. 규칙 기반 결과를 AI가 선택한 실험으로 제시하면 안 됩니다. 과거 105/105·280/280 검증과 이번 실행은 별도입니다.

## 원시 기록

- Daytona 전체 실행: `runs/20260919-140711-e5d205/summary.json`, 같은 폴더의 `events.jsonl`.
- OpenAI 연동 시도: `runs/20260919-140321-917bb3/summary.json`. 실제 Daytona baseline 2개는 통과했으나 첫 LLM 호출에서 중단.
- 로컬 전체 실행: `runs/20260919-140331-0ed435/summary.json`.
- 가상환경 로컬 smoke: `runs/20260919-140826-8d6f6c/summary.json`.

당시 OpenAI 잔액 오류의 세부 코드는 최소 진단 요청으로 확인했습니다. 충전 후의 성공 기록은 위 최신 검증을 따릅니다.

## 변경하지 않은 기존 코드

복사 원본과 SHA-256이 일치함을 확인했습니다.

- `models.py`: `697b5f3357f5dbecb4b367fcba49b3791b8dc155d477d417bc4184866d42bf66`
- `daytona_runner.py`: `fe79f10d954608d2910b7fc6635d2c72501ce99c3b6ea6604ea9d1918f50908f`
- `node_prep.py`: `747f5aafb1b4ec69b2366b740a92daf7db70684b0a8f001619d3d4e444a46287`
- `fixtures/repro.js`: `859ef1a81f8389ce3956c8eb2f05eaa9eb2cd63457a2b1228b3e0fbe90246040`

실행 코드·입력 JSON에 알려진 경계값이나 `65599`를 넣지 않았습니다. baseline 전체 관측은 audit에 남지만 첫 planner 입력에는 backingLength가 없습니다. API 키 값의 audit 로그 포함 여부도 검사했습니다.

## 해석 범위

실제 LLM의 COMPARE/SEARCH_BOUNDARY/STOP 전체 흐름은 로컬에서 확인했습니다. Daytona 전체 경계 검증 성공은 규칙 기반 기록이며, 실제 LLM + Daytona의 경계 확정 성공으로 바꿔 말하면 안 됩니다. 강제 프로세스 종료나 서비스 장애 시에는 TTL 보호가 있더라도 Daytona 대시보드에서 자원 상태를 확인하세요.
