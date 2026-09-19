# EnvBisect — 이해한 뒤 구현하는 Handoff

> ## 지금 필요한 부분만 읽으세요
>
> **처음 합류: §1–3만 읽기**
>
> **구현 중 막히면: §4–7 펼치기**
>
> **근거 확인은: §8–9 펼치기**

2026-09-19 · 개정 2 · 상세 수치·계약과 연구 근거는 아래 접힌 영역에 있다.

## 1. 어떤 일을 맡기는 제품인가

런타임을 업데이트한 뒤 CI가 실패했다. AI가 코드와 로그를 조사해 유력한 설명을 줘도, **그 설명이 이번 실패에 맞는지는 조건을 바꿔 실행해 확인해야 한다.** 사람은 이전 버전을 준비하고, 옵션을 바꾸고, 결과를 비교하고, 다음에 확인할 것을 정한다.

**EnvBisect는 이 실험 작업을 맡는 디버거다.** 재현 가능한 실패를 입력받아, AI가 다음 비교를 선택하고 Daytona가 조건별 실행 환경을 만든다. 결과를 다시 AI에 전달하며 실패 조건을 좁히고 통과한 변경을 기록한다. 사용자는 “이 조건에서 실패했고, 이 변경에서 테스트가 통과했다”는 실행 근거를 가져간다.

[Google의 재현 테스트 연구](https://arxiv.org/html/2502.01821v2#S6.SS2)와 [SaaS 현장 연구](https://www.sciencedirect.com/science/article/pii/S0164121226002943)는 실행·환경 정보의 실무 가치를 뒷받침한다. 이를 바탕으로 **환경 준비와 비교의 반복을 제품으로 제공하면 조사 부담을 줄일 수 있다**고 가정한다. EnvBisect의 고객 시간 절감은 아직 측정하지 않았다. 정확한 통계는 §8에 있다.

### “그냥 agent에 GitHub MCP를 붙이면?”에 대한 답

같은 기능을 갖춘 agent도 이 일을 할 수 있다. 차이는 모델의 지능이 아니라 **매번 직접 설계할 실험 운영을 제품의 기본 동작으로 제공하는가**다.

| 사용자가 맡기는 일 | 이 제품에서 맡는 구성 |
|---|---|
| 실패 코드·기존 CI 기록을 가져와 이해 | 입력 계층과 AI. 제품 목표는 CI 링크, 현재는 수동 RunBundle |
| 어떤 조건을 바꾸어 확인할지 정하기 | AI Planner + 허용된 실험 목록 |
| 각 조건의 실행 환경을 준비·분리하고 실행 | Daytona + runner |
| 같은 판정 기준으로 비교하고 다음 실험으로 이어가기 | Engine + 실행 결과를 받은 Planner |
| 결과를 다시 확인할 수 있게 남기기 | 조건·명령·버전·관측을 묶은 evidence export |

GitHub MCP에는 코드·Actions 기록 접근과 workflow 기능이 있고, CI도 dynamic matrix를 지원한다. 이들을 이용해 동일한 흐름을 구현할 수도 있다. **우리의 제품 주장은 조건 대조·다음 실험 선택·판정·종료·기록을 함께 제공한다는 것**이다. 설명만 출력하거나 고정 결과표만 실행하면 이 주장이 충분히 드러나지 않는다. [GitHub MCP](https://github.com/github/github-mcp-server) · [CI matrix](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations)

### Daytona의 가치가 실제로 나타나는 지점

```text
AI: “이 조건들을 비교하자”
             │
             ▼
Daytona: 조건별 임시 실행 환경
   ┌─────────┼──────────┐
 이전 버전   실패 버전   옵션을 바꾼 실패 버전
   실행        실행         실행
   └─────────┼──────────┘
             ▼
실행 결과 비교 → AI가 다음 실험 선택 → 새 환경·새 실행
             │
             ▼
실행 기록 보존 / 임시 환경 삭제
```

이는 구조 설명이며 모든 비교를 한 batch에서 실행한다는 뜻은 아니다. 실제 batch와 조건은 action을 따른다.

**독립 환경**은 실험 사이에 설치·설정이 섞이지 않도록 나눈다. **API 생성·실행·삭제**는 agent가 결정한 실험을 바로 실행 요청으로 바꾸게 한다. **준비 snapshot**은 같은 런타임의 반복 준비를 줄이는 선택 경로다. Daytona는 이 환경 운영을 application primitive로 제공해 구현 부담을 낮춘다. 다른 sandbox·컨테이너·CI로도 구축할 수 있으며, 고유 알고리즘이나 독점 능력이라는 주장은 아니다. [공식 snapshot 문서](https://www.daytona.io/docs/en/snapshots/)

## 2. 데모는 “정상 → 실패 → 변경 → 확인”으로 설명한다

### Demo A: 버전을 바꾸자 정상 작업이 예외로 끝났다

**사례의 출처:** Node 공개 버그 #65601을 작은 재현 프로그램으로 만든 뒤 사전 검증했다. 실제 고객 장애를 수집한 사례나 이번 문서 작성 중 새로 실행한 결과는 아니다.

| 순서 | 처음 보는 사람에게 할 설명 | 실행으로 확인한 사실 |
|---|---|---|
| 정상 | 메모리의 바이트 데이터를 숫자 배열로 바라보는 작업이 예외 없이 끝나야 한다 | 기존 Node 26.7.0에서 같은 코드·8 B 입력 통과 |
| 실패 | 런타임만 26.8.1로 바꾸자 예외가 발생했다 | pooled·implicit·Uint32 조건에서 RangeError |
| 비교 | 실패 버전을 유지하고 배열 길이 명시·메모리 할당 방식을 각각 바꿨다 | explicit length와 slow allocation에서 각각 통과 |
| 후속 조사 | 할당 방식에 따라 결과가 갈리니, 입력 크기가 바뀔 때도 시험한다 | 고정 실패 조건의 사전 인접 관측: 32767 B 실패 / 32768 B 통과 |
| 회복 후보 | 기존 수정 버전에서 같은 실패 케이스를 다시 확인한다 | 별도 사전 기록에서 26.9.0 통과 |

**개발자의 다음 행동:** 26.9.0 업그레이드 또는 통과한 사용 방식 변경을 후보로 검토하고, 자신의 앱 전체 테스트에서 확인한다. EnvBisect가 Node를 수정한 것은 아니다. 배열 생성 예외가 사라졌다는 검증과 애플리케이션 전체가 올바르다는 검증은 다르다.

**제품 데모의 핵심:** 위 결과를 사람이 미리 알고 있다는 사실과, AI가 새 관측으로 다음 실험을 선택하는 기능을 구분한다. 현장에서는 **실제 비교 결과 → 근거를 인용한 다음 선택 → 새 Daytona 실행**을 연결해야 한다. 26.9.0은 현행 초기 Planner domain 밖이므로 별도 RECORDED 카드로 보여준다.

### Demo B: 에러가 나지 않아도 계산값이 틀렸다

행렬과 그 역행렬을 곱하면 단위행렬에 가까워야 한다. 그런데 같은 이슈 행렬에서 SciPy 1.17.0의 inv·solve-auto는 최대 절대 오차 **9.107408**로 실패했다. 같은 버전·행렬에서 solver 옵션을 general로 바꾸면 **5.47e-16**, sym으로 바꾸면 **7.23e-16**로 통과했다. 이는 **기대 결과를 검사하고 옵션 변경을 대조하는** fallback이다. Node의 입력 크기 탐색과는 다른 사례다.

## 3. 이 이해를 오늘의 구현으로 옮긴다

| 준비된 것 | 120분 안에 새로 만들 것 | 이번 범위 밖 |
|---|---|---|
| 두 재현 코드·PASS/FAIL 판정 기준 | 수동 입력·실험 계약·실제 AI 호출 | CI 링크 자동 수집·임의 repo 자동 복원 |
| Daytona runner·Node 준비 helper | 선택된 조건을 실행으로 변환 | 자동 코드 수정·PR |
| Node Linux 105/105·SciPy Linux 45/45 사전 관측 일관 | 관측→다음 선택→새 실행의 loop·증거 출력 | 모든 root cause·모든 입력의 최소 조건 |
| 별도 snapshot 성능 측정 | 필요시 선택 경로 연결 | UI·snapshot 최적화를 핵심 연결보다 우선 |

표의 반복 수는 예상 PASS/FAIL과 일치한 관측 수다. 지원 대상은 **재구성할 수 있는 환경, 바꿀 수 있는 조건, 명확한 정답 검사**가 있는 실패다. 외부 production 상태·특정 GPU·확률적 race·성능 회귀는 현재 검증 범위 밖이다.

**세 체크포인트:** 45분에는 실제 대조 결과, 70분에는 그 결과를 받은 AI 선택, 95분에는 선택에 따른 새 실행이 있어야 한다. 첫 설명은 [Pitch Narrative](EnvBisect_Pitch_Narrative.md)를 사용한다.

---

<details>
<summary>구현할 때 펼치기 — 사전 검증표, 데이터 계약, 실행 경로, 120분 계획</summary>

## 4. 검증표 — 구현과 Q&A용 상세

이 절은 **기존 문서의 실행 기록**이다. 이번 재작성에서 새 Daytona 실행을 수행하지 않았다. Node·SciPy 수치는 원본 Handoff §6, snapshot은 원시 JSON과 대조했다. `105/105`·`45/45`는 예상한 PASS 또는 FAIL과 일치한 관측 수이며 제품 정확도·성공률이 아니다.

### Demo A · Node #65601 — 주력

Oracle: typed-array view 생성 성공은 PASS/exit 0, 예외는 FAIL/exit 1. Linux x86_64에서 공식 Node 바이너리를 SHA-256 manifest로 검증하고 변경하지 않은 `repro.js`를 실행했다. 각 칸은 **독립 Node 프로세스 5회**다.

| 조건 | 26.7.0 | 26.8.1 | 26.9.0 |
|---|---|---|---|
| 8 B / pooled / implicit / Uint32 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 8 B / pooled / explicit / Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B / slow / implicit / Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B / pooled / implicit / Uint8 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B / pooled / implicit / Uint16 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 32767 B / pooled / implicit / Uint32 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 32768 B / pooled / implicit / Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |

**3버전 × 7조건 × 5 = 105/105**. 3개 sandbox 안에서 총 105개 프로세스를 실행했다.

8 B pooled 입력의 backingLength는 버전 순서대로 **65536 / 65599 / 65600**. 26.8.1 Uint32 실패 메시지는 `RangeError: byte length of Uint32Array should be a multiple of 4`. 32768 B에서는 backing allocation이 32768 B였다. 이 값은 실행 증거이며 내부 구현 원인을 모두 규명한 결과는 아니다.

`pooled=Buffer.allocUnsafe`, `slow=Buffer.allocUnsafeSlow`이며 화면의 unpooled는 코드의 slow다. explicit length는 `Math.floor(size / BYTES_PER_ELEMENT)`이므로 모든 size에서 원래 view와 동치인 수정이라고 부르지 않는다.

Windows는 26.7.0/26.8.1/26.8.2/26.9.0 × 7조건 × 10 = **280/280**. **Linux의 실패 버전은 26.8.1로 한정**한다. 결과 표현은 고정 조건에서 관측한 인접 전환 **32767 B FAIL / 32768 B PASS**이며 전역 최소·전역 단조성을 뜻하지 않는다. [공개 이슈](https://github.com/nodejs/node/issues/65601)

### Demo B · SciPy #24359 — fallback

동일 complex symmetric, non-Hermitian 행렬에 `np.allclose(A_inv @ A, I, rtol=1e-10, atol=1e-10)`로 판정. 오차는 `max(abs(A_inv @ A - I))`. Linux 실제 runtime은 **Python 3.14.4 / NumPy 2.3.5**다. 생성 요청의 `python:3.13-slim` 라벨과 다르므로 실제 출력 기준으로 말한다.

| 조건 | 결과 | 최대 절대 오차 | 반복 |
|---|---|---:|---|
| 1.16.3 / 이슈 행렬 / inv | PASS | 5.57e-16 | 5/5 |
| 1.17.0 / 이슈 행렬 / inv | FAIL | 9.107408 | 5/5 |
| 1.17.1 / 이슈 행렬 / inv | PASS | 7.23e-16 | 5/5 |
| 세 버전 / Hermitian control / inv | 모두 PASS | 각 1.11e-16 | 각 5/5 |
| 1.17.0 / 이슈 행렬 / solve-auto | FAIL | 9.107408 | 5/5 |
| 1.17.0 / 이슈 행렬 / solve-general | PASS | 5.47e-16 | 5/5 |
| 1.17.0 / 이슈 행렬 / solve-sym | PASS | 7.23e-16 | 5/5 |

**9조건 × 5 = 45/45**. Windows는 Python 3.13.5 / NumPy 2.3.5, 15조건 × 10 = **150/150**이며 Linux와 조건 집합이 다르다. 같은 행렬의 solver assumption 변경이 통제된 대조다. Hermitian control은 계수도 다르고, Demo B에는 Node형 size 경계 주장을 붙이지 않는다. [공개 이슈](https://github.com/scipy/scipy/issues/24359)

### 지연·snapshot — loop와 별도 측정

| 측정 단위 | 사전 결과 |
|---|---|
| Node Windows: 전체 프로세스 / oracle 내부 중앙값 | 137 ms / 0.0095 ms |
| Node Linux: oracle 내부 중앙값 / 5프로세스 case batch | 0.0031 ms / 0.74–0.92 s, 중앙값 0.79 s |
| Node Linux: 3 sandbox 병렬 gate, 각 35프로세스, 준비·삭제 포함 | 13.54 s |
| SciPy Linux: oracle 명령 왕복 / 2버전 각 10회 병렬, 설치·삭제 포함 | 중앙값 1.48 s, 범위 1.37–2.48 s / 25.07 s |
| 기본 경로: 1 world lifecycle / 4 world 병렬 wall time | **12.069 s / 11.153 s** |
| 준비 snapshot: 1 world lifecycle / 4 world 병렬 wall time | **6.191 s / 2.614 s** |
| snapshot 일회성 준비 / 요청 후 active 대기 | **36.652 s / 26.541 s** |

snapshot 비교는 같은 8 B 실패 케이스의 **10개 probe**이며 모두 v26.8.1·exit 1·backingLength 65599, 삭제 완료. 4개 fan-out의 비율만 약 **4.27배**다. 전체 matrix·자동 loop 성능은 미측정. warm pool 생성은 HTTP 404여서 성능 측정이 없다.

snapshot `envbisect-node-2681-spike-20260918154602`는 준비된 filesystem·Node 26.8.1·fixture만 담았고 생성 당시 active였다. 현재 상태는 재확인한다. **runner에는 snapshot selector가 없다.** 초반에 별도 경로를 연결·검증할 수 있을 때만 사용하고, 기본 경로를 유지한다. 26.7.0/26.9.0을 이 snapshot으로 대체하지 않는다. [원시 JSON](sources/snapshot_latency_results.json)

## 5. 구현 계약: Planner는 선택, Engine은 판정

```text
수동 RunBundle → good/bad 실제 재현 → Planner → validated Action
                                              ↓
                                     Engine → WorldSpec[]
                                              ↓
                                        Daytona Runner
                                              ↓
Planner ← evidence projection + world_id join ← Observation[]
   └─ STOP → 조건·실행 명세·관측·action history를 export
```

world는 특정 조건의 실행 단위, fixture는 작은 재현 프로그램, oracle은 PASS/FAIL 검사다. UI의 CI URL은 `Prepared demo input`으로 표시한다.

| 신규 계약 | 필수 필드·규칙 |
|---|---|
| RunBundle | `good_world, bad_world, observed_differences, factors` |
| Factor | `id, kind, source, domain, manipulable`; kind는 categorical/integer/boolean |
| ExperimentAction | `action, factor, values, fixed, reason`; 정확히 `COMPARE / SEARCH_BOUNDARY / STOP` 중 하나 |
| COMPARE | values는 완전한 개입 조합 목록, fixed는 나머지 조건. factor는 여러 축 가능 |
| SEARCH_BOUNDARY | factor는 정수 축 하나, values는 관측된 실패 seed·허용 범위. 경계 답은 포함하지 않음 |
| STOP | 현재 증거와 종료 이유. 별도 VERIFY action 없이 Engine이 재검증 |

초기 good/bad는 `{node:26.7.0/26.8.1, size:8, allocation:pooled, length:implicit, width:32}`. **observed difference는 node뿐**이며 PASS/FAIL은 outcome이다. 허용 intervention은 allocation `[pooled,slow]`, length `[implicit,explicit]`, width `[8,16,32]`, size `[1,100000]`. size는 처음부터 조작 가능하지만 아직 관련성이 확인된 축이 아니다.

`backingLength`는 원시 baseline 로그에 있더라도 **초기 Planner projection 및 factor 목록 전체에서 제외**하고 Round 1 후 discovered evidence로 추가한다(`manipulable=false`). 숫자 domain 상한은 실행 한도다. fixture의 알려진 경계·expected outcome을 prompt·hidden config에 넣지 않는다.

**Planner 정책:** 허용 domain과 실제 관측·예산만 받고, 저비용 범주 대조로 조건을 구분한 뒤 근거가 있을 때 숫자 축을 탐색한다. reason은 observation ID를 인용한다. 유효하지 않은 action은 제한된 repair 또는 STOP. 실험 순서 자체를 Node 전용 답안으로 고정하지 않는다.

**Engine 책임:** domain·fixed·예산 검사 → 검증된 template으로 명령 구성 → 실행·중복 cache → 증거 검증 → 탐색·재검증. Planner가 자유 shell이나 PASS/FAIL을 작성하지 않는다.

### 기존 runner 계약 — 재사용할 부분

| API | 정확한 연결점 |
|---|---|
| Upload | `Upload(source: Path, destination: str)` |
| WorldSpec | 필수 `world_id, runtime, command`; 선택 `image=None, env={}, factor_values={}, timeout_seconds=30, uploads=()` |
| ExperimentBatch | `worlds: tuple[WorldSpec,...]`, `max_parallel=4`, 허용 1–4 |
| run_one / run_batch | 단일 world lifecycle / thread pool, 결과는 입력 순서의 tuple |
| Observation | `world_id, status, exit_code, stdout, duration_seconds, create_seconds, upload_seconds, execute_seconds, delete_seconds, deleted, evidence, error` |

runtime·factor_values는 **메타데이터**다. command가 실제 실행을 결정한다. Observation에 factor_values가 없으므로 **world_id로 원래 WorldSpec과 join**한다. evidence는 stdout의 마지막 JSON object이며 없으면 `{}`. 전체 stdout은 audit에 보존한다.

runner는 exit 0→PASS, 그 외→FAIL; fixture status 충돌·요청/생성/파싱/삭제 실패→ERROR. 키·`requests` 누락은 `DaytonaUnavailable`이 batch 밖으로 전파될 수 있고 retry는 없다. **Engine은 exit 누락·필수 evidence 누락·실제 runtime/factor 불일치·deleted=false를 유효한 FAIL로 세지 않는다.** 진단 결과는 INCONCLUSIVE이며 Observation enum은 PASS/FAIL/ERROR 그대로다.

HTTP timeout은 create 90초, 파일 upload 45초, execute는 command timeout+30초, delete 60초. 명령 기본 30초, 기존 Node 예제는 180초다. 무대 전체 예산은 별도로 제한하고, 로컬 대기 종료를 원격 취소·삭제 완료로 해석하지 않는다.

### 검증된 Node 실행 경로

기존 코드 패키지의 `sources/envbisect-spike`를 ROOT로 삼는다. 현재 문서 묶음의 `sources/`에는 참고 원문만 있고 실행 코드는 포함하지 않았다. 아래는 **기존 코드 패키지 루트**에서 시작하는 명령이다. 현재 프로세스에 기존 인증 방식으로 `DAYTONA_API_KEY`를 준비한다.

```powershell
python -c "import requests; print('requests ready')"
python sources/envbisect-spike/envbisect/smoke_test.py
```

requests가 없다면 프로젝트 가상환경에 설치한다. smoke는 접근·명령·삭제 확인이며 fixture/loop 테스트는 별도다. Linux gate는 **image=None + 공식 바이너리 다운로드·hash 검증** 경로였다. `fixture_adapter.node_world(...)`의 verified_image 경로는 gate 미검증이므로 해당 매핑만 연결하거나 아래 예제를 사용한다.

```python
from pathlib import Path
import sys
ROOT = Path("sources/envbisect-spike").resolve()  # 기존 코드 패키지 루트 기준
sys.path.insert(0, str(ROOT / "envbisect"))
from models import Upload, WorldSpec
spec = WorldSpec(
    world_id="r1-u32", runtime="node-26.8.1", image=None,
    factor_values=dict(node="26.8.1", size=8, allocation="pooled", length="implicit", width=32),
    uploads=(Upload(ROOT / "node_prep.py", "node_prep.py"),
             Upload(ROOT / "envbisect/fixtures/node_65601/repro.js", "repro.js")),
    timeout_seconds=180,
    command="python3 node_prep.py 26.8.1 && /tmp/node-fixture repro.js --size=8 --allocation=pooled --length=implicit --width=32",
)
```

후속 world는 validated action에서 값들을 받아 구성한다. 실제 `evidence.node == 'v26.8.1'` 및 factor·exit·oracle·삭제 상태를 확인한다. 전체 예제는 [기술 원문 §3](sources/HACKATHON_HANDOFF.original.md)에 있다.

## 6. Round 0 → Round 1 → Round 2

**Round 0:** 같은 fixture·size 8·pooled·implicit·width 32로 26.7.0 PASS / 26.8.1 FAIL을 실제 재현한다. baseline이 다르면 reconstruction 문제로 종료한다.

**Round 1:** 아래는 검증된 대조 예시다. Planner가 다른 합리적 batch를 선택할 수 있다. 모두 26.8.1·size 8 고정이며 나머지는 원래 실패 조건과 한 축씩 비교한다.

| world_id | 개입 | 사전 결과 | backingLength |
|---|---|---|---:|
| r1-explicit | pooled / explicit / Uint32 | PASS | 65599 |
| r1-unpooled | slow / implicit / Uint32 | PASS | 8 |
| r1-u8 | pooled / implicit / Uint8 | PASS | 65599 |
| r1-u32 | pooled / implicit / Uint32 | FAIL | 65599 |

이 결과는 버전 하나로 실패를 설명할 수 없음을 보여준다. Planner 입력은 world_id, join한 factors, status·exit, 선택 evidence(`node, backingLength, error, viewLength`), 시간·cleanup이다. 다음은 **예시 action**이며 실제 응답을 대신하지 않는다.

```yaml
action: SEARCH_BOUNDARY
factor: size
values: {seed_observed_bad: 8, min: 1, max: 100000}
fixed: {node: '26.8.1', allocation: pooled, length: implicit, width: 32}
reason: 'r1-u32 FAIL, r1-explicit/r1-unpooled/r1-u8 PASS. 고정 실패 조건에서 size의 영향을 시험한다.'
```

**Round 2 Engine:** 같은 fixed에서 seed FAIL 확인 → size를 배수로 키워 PASS endpoint 확보 → FAIL/PASS bracket 이분 탐색 → 인접 정수 endpoint를 **새 프로세스로 각 5회** 재검증. probe budget은 endpoint 검증 10회를 포함해 정하고, 실제 world·프로세스·batch 수와 시간을 집계한다.

최대 4개 probe 병렬 bracket 탐색은 후속 제안이며 미구현·미검증이다. 선택하면 정렬된 관측으로 후보 구간을 줄인다. 4개 내부 probe는 최대 5개 구간을 만든다. 중복 size를 피하고 예산·단일 전환 가정을 검사한다. 순차 기준 구현부터 완성해도 된다.

**종료:** 인접 조건을 반복 확인하면 `FAILURE CONDITION VERIFIED / Observed transition under fixed conditions`. ERROR·증거 누락·예산 소진·endpoint flip·단일 전환 가정 모순이면 INCONCLUSIVE. 알려진 32767/32768을 결과에 채우지 않는다. 2개 고수준 round에도 여러 batch가 필요하므로 3분 내 전체 탐색은 리허설로 판단한다.

**Export:** RunBundle, fixture hash, WorldSpecs, 원시 Observations, join된 evidence, action history, fixed 조건·endpoint 반복 수, 실험/시간 집계, 종료 이유·검증 범위. root cause·전역 최소를 입증하는 패키지가 아니다.

## 7. 120분 실행표와 실패 시 전환

| 시간 | 담당·작업 | 완료 기준 |
|---|---|---|
| 0–10 | 함께 접근·smoke·기존 근거 확인; snapshot 짧게 판단 | 생성·실행·삭제, 코드와 fixture 준비 |
| 10–25 | A: contracts·수동 RunBundle; B: runner 연결 | invalid action/domain 거부 |
| 25–45 | B: COMPARE; A: projection | 4 world 실제 관측 및 runtime·cleanup 검증 |
| 45–70 | A: Planner, B: Engine 통합 | 실제 관측 ID를 인용한 다음 action |
| 70–95 | B: 탐색·재검증; A: action/evidence loop | 새 실행으로 bracket 또는 INCONCLUSIVE |
| 95–110 | 함께 CLI·export·발표 흐름 | good/bad→대조→다음 축→실행 결과 추적 |
| 110–120 | 함께 리허설·freeze | 165초 설명 + 15초 여유, fallback 확정 |

한 명이면 같은 순서로 진행한다. 재사용: `models.py, daytona_runner.py, smoke_test.py, node_prep.py, repro.js`. 신규: `contracts.py, planner.py, experiment_engine.py, demo.py`, RunBundle 파일. adapter 변경은 검증 경로 연결에 한정한다. 행사 공지에 따라 사전 준비물과 당일 구현 범위를 구분해 설명한다.

| 상황 | 즉시 할 일 |
|---|---|
| baseline 미재현 / runtime·oracle·evidence 불일치 | 진단 중단, INCONCLUSIVE와 누락 context 표시 |
| deleted=false | 추가 fan-out 중단, 남은 자원 확인 |
| Planner 불가 / invalid action 지속 | MANUAL로 명시하거나 STOP; 70분 이후 UI 생략 |
| 탐색 예산 소진 / 모순 | 현재 유효 관측·구간 보존, INCONCLUSIVE |
| 95분까지 자동 loop 미완성 | 실제 구현 범위만 발표; adaptive 완성 주장 제외 |
| snapshot 불가 / A 불안정 / 네트워크 지연 | 기본 경로 / Demo B / RECORDED 명시로 전환 |

무대 핵심은 **대조 결과 → 증거를 인용하는 다음 action → 새 실행의 조건**이다. CLI로 충분하다. LIVE·RECORDED·MANUAL을 표시하고 자동 CI ingestion·Add-to-CI는 연결된 기능처럼 보이지 않게 한다. 처음 설명할 이야기와 발표 운영은 [Pitch](EnvBisect_Pitch_Narrative.md)를 사용한다.


</details>

<details>
<summary>근거를 확인할 때 펼치기 — 연구 통계와 원본 위치</summary>

## 8. 외부 근거 — 수치가 필요할 때만

개발자는 실패 로그를 받은 뒤에도 환경 준비, 한 조건 변경, 재실행, 결과 비교를 반복한다. 연구와 제품 사례는 재현 정보·실행 맥락의 가치를 뒷받침한다. **우리의 제품 가설은 이 반복의 다음 실험 선택까지 자동화하면 조사 부담을 줄일 수 있다는 것**이다.

| 근거·원문 확인 위치 | 확인한 사실 | 적용 범위 |
|---|---|---|
| **E1 · Wang 등, Application monitoring… Action research study**, [출판사 Abstract](https://www.sciencedirect.com/science/article/pii/S0164121226002943), DOI `10.1016/j.jss.2026.113061` | Lentune에서 2024.7–2025.10, 5회 개선 주기. 재현 불가 버그 33%→0%, 평균 closure 60→15일. bug-specific·contextual evidence를 함께 수집 | 단일 SaaS 기업의 모니터링·교육·업무 개선 복합 개입. 환경 정보만의 인과 효과나 산업 평균이 아니다. 출판사 초록과 대조했고 본문 표는 미확인. 권호 표기는 2027.1이며 확인일에 초록이 공개돼 있다. |
| **E2 · Cheng 등, Agentic Bug Reproduction… at Google**, [2025 v2 §5.2.2·§6.2](https://arxiv.org/html/2502.01821v2#S6.SS2) | 전체 연구 80개 버그 중 BRT가 생성된 **23개**에서 Passerine의 plausible fix 확보가 **13/23→17/23**. 논문은 약 30% 상대 증가로 표현 | oracle BRT 통과 후보 기준. 정답 패치로 BRT의 plausibility를 검증한 하위집합이므로 저자도 효과의 상한으로 설명한다. 30%p 향상·전체 80개 효과로 말하지 않는다. |
| **E3 · Liu 등, A First Look at Bugs in LLM Inference Engines**, [2026-01 v2 §5.1.4·Table 7·§7.3](https://arxiv.org/html/2506.09713v2#S7) | 5개 엔진·929개 버그. backend·version·dependency 환경 문제를 분류. 환경 범주 해결 기간 평균 **37.8일**, 중앙값 **7.4일**; configuration은 **42.3일 / 8.8일** | 생성→종료 기간으로 조사·대기·리뷰 등을 포함하며 순수 작업 시간이 아니다. 복수 원인 분류이므로 범주 수를 단순 합산하지 않는다. EnvBisect의 GPU 지원 증거도 아니다. |
| **E4 · Jin 등, Automated Modernization… Notebooks**, [2026 preprint §2.1, Table 1, §2.2](https://arxiv.org/html/2602.07195v1#S2) | 79개 Kaggle 대회에서 선별한 12,720개 notebook 중 **35.4%** 재현; dependency backporting 후 **35.1%** | 점수 상대 편차 ≤10% 기준이며 단순 무오류 실행률이 아니다. 모든 실패를 dependency drift로 돌릴 수 없고 환경 복원만으로 해결된다는 근거도 아니다. |
| **E5 · Replay**, [공식 Individual Debugging 제품 설명](https://www.replay.io/debugging) | 실행 기록·상태·네트워크 정보를 사람이 조사하거나 coding agent에 제공하는 제품이 존재 | 실행 증거를 가치로 제안하는 시장 신호. 매출·지불 의사·EnvBisect 시장 규모를 입증하지 않는다. |

보조 근거: [Rahman 등, ICSME 2020 / arXiv 2021, Abstract](https://arxiv.org/abs/2108.05316)는 Firefox·Eclipse의 재현 불가 보고서 **576개**, 전문 개발자 **13명**을 조사해 정보 재요청·수동 검색 부담을 보고했다. 오래된 연구이므로 최신 비율로 인용하지 않는다. 외부 자료 재확인일은 모두 2026-09-19다.

**해커톤 이후 확인할 것:** 검증 조건까지 걸린 시간, 사람 개입 횟수, 실험 수·비용, INCONCLUSIVE 비율, 회귀 테스트 활용률. 현재 고객 대상 절감 효과와 지불 의사는 미측정이다.

## 9. 출처와 원본을 찾는 법

**내부 기준:** [기존 Handoff](sources/EnvBisect_Handoff.original.md) §6=Node·SciPy·시간, §8=runner, §10=snapshot; [Field Guide](sources/EnvBisect_Field_Guide.original.md)=현장 계약; [기술 Handoff](sources/HACKATHON_HANDOFF.original.md)=정확한 API·WorldSpec·탐색 의사코드; [snapshot raw JSON](sources/snapshot_latency_results.json)=정밀 시간·10 probe·404. 네 파일은 첨부 원본 사본이다.

Node·SciPy 원시 gate JSON과 실행 코드는 기존 코드 패키지에서 확인한다: `envbisect-spike/DAYTONA_NODE_RESULTS.md`, `DAYTONA_SCIPY_RESULTS.md`, `daytona_node_26_7_0.json`, `daytona_node_26_8_1.json`, `daytona_node_26_9_0.json`, `daytona_scipy_1_16_3.json`, `daytona_scipy_1_17_0.json`, `daytona_scipy_1_17_1.json`. 이번에는 이 개별 raw 파일을 직접 다시 열지 않았으며, 수치는 첨부 Handoff를 근거로 유지했다. 초기 `RESULTS.md`의 BLOCKED 기록보다 후속 gate 보고서가 최신이다.

외부 근거의 링크·원문 위치·해석 한계는 §8에 함께 표기했다. 외부 연구 통계, 우리 fixture 관측, 미구현 설계는 서로 다른 근거다.

</details>
