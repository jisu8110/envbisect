# EnvBisect 해커톤 인수인계

신규 팀원을 위한 제품의 본질과 구현 및 발표 가이드

기준일 2026년 9월 19일 KST · 문서 버전 1.0

## 1 처음 합류한 팀원에게

EnvBisect는 **재현 가능한 조건부 CI 실패를 대상으로, 실행 증거를 보며 다음 실험을 선택하는 디버깅 도구**다. 실패한 코드에 대한 설명보다 먼저 “어떤 조건을 바꾸면 실패가 사라지는가”를 확인한다. CI 이후 엔지니어가 직접 하던 환경 준비, 조건 변경, 재실행, 결과 비교, 다음 가설 선택의 반복을 제품으로 만든다.

> EnvBisect is an experimental debugger for conditional CI failures.
>
> The LLM chooses the experiment. Daytona creates the worlds. Execution decides what's true.

해커톤 직전까지 확보한 것은 두 개의 실제 회귀 버그 fixture와 Daytona 실행 기반이다. Node Demo A는 Linux에서 105개 관측, SciPy Demo B는 45개 관측이 예상한 PASS/FAIL과 일치했다. **LLM Planner, 적응형 루프, 자동 경계 탐색은 아직 구현되지 않았다.** 120분 동안 새로 만들 핵심은 Round 1의 관측을 Planner에게 전달하고, 그 선택으로 Round 2의 새 Daytona 실험을 실행하는 연결이다. [S1][S4][S5]

발표의 결정적 장면은 `32767 B FAIL / 32768 B PASS`라는 숫자만이 아니다. **앞선 실험 결과 때문에 다음에 탐색할 변수가 선택되는 순간**을 보여줘야 한다. 그 장면이 실제로 작동해야 EnvBisect의 제품 주장이 성립한다.

이 문서에서 CI는 코드 변경 때 테스트를 자동 실행하는 시스템이다. **world**는 특정 환경과 입력 조건의 실행 단위, **fixture**는 버그를 작게 재현하는 프로그램, **oracle**은 그 실행의 통과와 실패를 결정하는 검사다. **factor**는 바꿔 볼 변수이고, **intervention**은 그 변수에 실제로 가하는 변경이다. **Observation**은 실행에서 얻은 결과 기록이다.

### 읽는 순서

- 5분 온보딩: 이 장, 2~4장, 6장과 12장.
- 구현 담당: 7~11장과 원본 `HACKATHON_HANDOFF.md`.
- 발표 담당: 12~15장과 별도 `EnvBisect_Field_Guide.md`.
- 수치 확인: 5~6장, 10장, 17장의 근거 목록 및 `sources/` 원본.

### 지금 확정된 상태

| 영역 | 확보한 것 | 당일 할 일 |
|---|---|---|
| Demo A | Node #65601, Windows 280/280 및 Daytona Linux 105/105 일관 | 현재 접근과 핵심 조건을 다시 확인 |
| Demo B | SciPy #24359, Windows 150/150 및 Daytona Linux 45/45 일관 | A 실패 시 사용할 실행 경로 준비 |
| 실행 기반 | REST runner, 파일 업로드, 환경변수, 최대 4개 병렬 실행, 삭제 시도 | 검증된 Node 준비 경로를 engine에 연결 |
| 실험 판단 | 데이터 계약과 Planner 정책 문서 | 실제 모델 호출 및 출력 검증 |
| 경계 탐색 | 순차 탐색 의사코드, 이후 병렬 탐색 제안 | 예산 내 탐색과 양 끝 재검증 |
| snapshot | 26.8.1 준비 snapshot의 별도 성능 실측 | 선택적 연결 및 현재 상태 재확인 |
| 제품 입출력 | CI 링크 UX 및 evidence package 설계 | MVP는 수동 RunBundle과 CLI부터 |

`105/105`, `45/45`는 성공률이나 모든 버그에 대한 정확도가 아니다. **예상한 PASS 또는 FAIL과 일치한 반복 관측 수**다. 해당 관측마다 새 sandbox를 만든 것도 아니다. Node gate는 3개 sandbox 안에서 총 105개 독립 Node 프로세스를 실행했다. [S4][S5]

## 2 왜 이 문제를 풀려고 하는가

CI가 어제는 통과하고 오늘은 실패했다고 하자. 로그가 알려주는 것은 실패 지점과 오류 메시지다. 엔지니어는 그다음 “런타임 업데이트 때문인가”, “특정 옵션 때문인가”, “입력 크기가 바뀌어서인가”를 시험한다. 버전을 바꾸려면 환경을 준비해야 하고, 여러 조건을 동시에 바꾸면 무엇이 영향을 줬는지 다시 분리해야 한다. 실험 결과가 다음 행동으로 이어지지 않으면 같은 확인을 반복하기 쉽다.

EnvBisect가 줄이려는 노동은 이 반복이다. 사용자가 원하는 결과는 그럴듯한 설명 한 문장보다 **같은 실패를 재현하는 조건, 바로 옆의 통과 조건, 실행 기록**이다. 이 결과는 버그 리포트, 수정 작업, 회귀 테스트 설계에 넘길 수 있다. 자동 패치까지 만들지 않아도 재현 조건을 좁히는 데 가치가 있다.

### 문제의 실재성과 사업 가설을 구분한다

Node와 SciPy의 실제 공개 이슈 및 반복 실행은 “버전 하나만으로 실패를 충분히 설명할 수 없고 입력이나 실행 옵션과 함께 봐야 하는 문제”가 존재한다는 직접 근거다. 그러나 이 두 사례가 EnvBisect의 시장 규모, 지불 의사, 평균 시간 절감, 일반 버그 해결률까지 증명하지는 않는다. 현재는 제품 가설이며 고객 검증은 남아 있다. [S2][S4][S5][S6]

이전 대화에서는 재현 실패 연구, runtime diagnosis 연구, Replay와 같은 실행 기록 도구도 검토했다. 그 논의의 의미는 “LLM에게도 실행 맥락과 재현 증거가 필요하다”는 문제의식이다. 출처가 다시 확인되지 않은 연구 통계는 발표 성과 수치로 사용하지 않는다. 해커톤에서는 직접 보유한 반복 실행 증거로 문제를 설명한다.

### 우선 사용자와 사용 순간

첫 사용자는 런타임 또는 의존성 업데이트 뒤 결정적으로 실패하는 테스트를 가진 개발자, 라이브러리 유지보수자, CI 담당자다. “실패는 확인했지만 어떤 조건이 필요한지 모르는 순간”에 켠다. 장애의 모든 상태를 복원하거나 모든 버그를 자동 수정하는 도구를 목표로 시작하지 않는다.

제품이 유용한지 다음 단계에서 확인할 지표는 첫 재현까지 걸린 시간, 검증된 조건까지 걸린 시간, 사람이 개입한 횟수, 실행한 실험 수, INCONCLUSIVE 비율, 결과를 실제 회귀 테스트로 사용한 비율이다. 현재 이 지표의 사용자 대상 실측치는 없다.

## 3 기존 도구와의 관계

### CI 이후의 진단 작업

일반 CI는 정해 둔 테스트와 환경 조합을 실행하고 결과를 알려준다. EnvBisect는 이미 발생한 실패에서 출발해, 이전 실행 결과를 바탕으로 다음 실험을 정하고 조건을 좁힌다. CI는 입력이자 결과를 다시 돌려줄 곳이다.

GitHub Actions도 이전 job의 출력과 `fromJSON`으로 동적 matrix를 만들 수 있다. 그러므로 “CI는 동적으로 실행할 수 없다”는 차별화는 틀리다. EnvBisect의 주장은 **실험 선택 정책, 실행 가능한 개입 목록, 결정적 판정, 증거 연결, 중단 조건을 하나의 진단 흐름으로 제공한다**는 것이다. CI 위에서도 이 흐름을 직접 구현할 수 있다. [W3]

### LLM debugger와 coding agent

코드와 로그를 읽는 LLM은 가설을 제안할 수 있고, 실행 도구를 가진 coding agent는 재현 실험도 할 수 있다. “LLM은 실행을 못 한다”거나 “다른 agent는 이 버그를 못 푼다”고 주장하지 않는다. EnvBisect는 그 능력을 제한된 실험 계약과 감사 가능한 결과로 조직한다. 모델은 다음 실험을 제안하고, 실제 runtime과 oracle이 낸 결과만 관측으로 받아들인다.

Planner의 좋은 답은 “원인은 buffer alignment입니다”가 아니라 “이 관측들이 allocation 경로의 관련성을 시사하므로 다른 조건을 고정하고 size를 탐색하겠습니다”다. 원인 설명은 해석이고, PASS/FAIL 및 인접 경계는 실행으로 확인한 사실이다.

### bisect와 기존 실험적 디버깅

버전 bisect와 delta debugging은 이미 알려진 탐색 축이나 실패 유발 차이를 테스트로 좁히는 접근이다. EnvBisect는 이 철학을 따른다. 새로운 탐색 알고리즘의 발명이나 최초의 counterfactual sandbox 제품이라고 포지셔닝하지 않는다. 강조할 것은 **증거에 따라 어떤 축을 탐색할지 선택하는 사용자 흐름**이다.

| 도구 또는 접근 | 주로 답하는 질문 | EnvBisect와의 연결 |
|---|---|---|
| CI와 matrix | 지정한 테스트와 조합이 통과하는가 | 실패 사건과 기존 결과 제공 |
| LLM 및 coding agent | 무엇이 잘못됐고 어떻게 고칠까 | 실험 후보 선택, 이후 수정에 증거 활용 |
| 버전 bisect | 선택한 버전 또는 commit 축의 어디서 바뀌나 | engine의 결정적 탐색 방식 |
| 실행 기록 및 replay | 실제 실패 실행에서 무엇이 일어났나 | 원 실행 맥락과 증거 제공 가능 |
| EnvBisect | 다음에 무엇을 시험하고 어떤 조건에서 실패하나 | 관측 기반 선택과 실제 실행의 반복 |

## 4 Daytona가 제품에서 맡는 일

Daytona는 실험 요청을 격리된 실행 환경으로 바꾸는 기반이다. EnvBisect는 WorldSpec을 만들고, runner는 sandbox 생성, 파일 업로드, 명령 실행, 결과 수집, 삭제를 수행한다. 서로 다른 런타임을 병렬로 시험하면서 각 결과를 같은 형식의 Observation으로 받는다. 준비 snapshot은 동일한 파일시스템과 런타임을 출발점으로 여러 환경을 만드는 데 쓸 수 있다. [S1][S4][W1]

**Daytona-native 가치**는 모델이 새 실험을 선택하는 즉시 실제 실행 환경을 수명 주기까지 포함해 다룰 수 있다는 점이다. 사용자는 실험마다 별도 서버를 관리하지 않고, 제품은 생성부터 삭제까지의 시간과 결과를 기록한다. snapshot을 쓰면 반복되는 런타임 준비를 줄일 가능성이 있으며 이번 spike에서 이를 측정했다.

Docker, VM, Kubernetes, 다른 sandbox 공급자로도 유사한 시스템을 만들 수 있다. 따라서 “Daytona에서만 기술적으로 가능하다”는 독점 주장은 근거가 없다. 이 프로젝트에서 실제로 검증된 통합 대상이 Daytona이고, 실험을 위한 임시 컴퓨터를 애플리케이션에서 요청하는 구조가 Daytona와 자연스럽게 맞는다는 것이 정확한 설명이다.

### 이번에 실제 사용한 기능

- 기본 Linux sandbox 생성, 명령 실행 및 stdout과 exit code 수집.
- fixture와 런타임 준비 파일 업로드, 환경변수 전달.
- 최대 4개의 WorldSpec 병렬 처리와 실행 후 삭제 시도.
- 별도 spike에서 준비된 filesystem snapshot 생성 및 4개 sandbox fan-out.

runner가 하는 삭제는 `finally`의 **삭제 시도**다. 삭제 성공을 보장하지 않으며 실패하면 `ERROR`, `deleted=false`로 기록한다. snapshot도 네트워크 상태, 외부 서비스, 모든 머신 상태의 완전한 재현을 보장하는 것으로 설명하지 않는다. [S1][S7][S8]

> Daytona gives every hypothesis an isolated world to run in.

이 문구는 개념 설명이다. 실제 구현에서는 검증된 도메인의 실행 가능한 개입만 world로 만든다.

## 5 여기까지 온 결정의 흐름

처음에는 EnvBisect와 SideEffect CI를 후보로 비교했다. 짧은 시간 안에 문제와 결과를 보여주기 쉽고, 실행 환경 비교가 제품 메커니즘과 직접 연결된다는 이유로 EnvBisect를 깊게 준비하는 방향으로 좁혔다. SideEffect CI는 당시의 대안 아이디어이고, 현재의 **Demo B는 같은 EnvBisect 제품을 보여주는 SciPy fixture**다. 둘을 혼동하지 않는다. [C1]

| 단계 | 결정과 근거 | 현재 해석 |
|---|---|---|
| 문제 탐색 | 환경 또는 조건에 따라 달라지는 실패에 주목 | CI 이후의 수동 실험 노동을 제품 대상으로 정의 |
| 초기 SciPy 후보 | #25692의 Python 및 NumPy 조합을 재현하려 했으나 설치 조합을 검증하지 못함 | 보류된 후보이며 성공 사례로 사용하지 않음 |
| SciPy 대안 | #24359의 동일 행렬과 solver 옵션 비교를 Windows에서 검증 | 이후 Daytona Linux 45/45로 Demo B 고정 |
| Node 후보 선정 | 작은 fixture, 빠른 실행, 명확한 조건 상호작용과 인접 size 결과 | Windows 280/280 뒤 Linux 105/105로 Demo A 채택 |
| 기반 freeze | REST runner와 fixture의 실행 경로 검증 | 해커톤에서 새로 만들 것은 closed loop |
| 데이터 모델 정리 | 초기 차이, 조작 가능한 변수, 실행 후 증거 구분 | node만 observed difference, size는 available intervention |
| snapshot 측정 | 4개 병렬 wall time 11.153초와 2.614초 비교 | 선택적 빠른 경로이며 의존성으로 만들지 않음 |
| 발표 설계 | 네 장면과 evidence에서 다음 실험으로 넘어가는 순간 | CLI로도 표현 가능, UI는 추가 여유가 있을 때 |

초기 `envbisect-spike/RESULTS.md`와 첨부 당시의 `RESULTS.md`에는 Daytona 접근 차단 또는 Linux 미검증이라고 적혀 있다. 그 기록은 당시에는 맞았다. 이후 `DAYTONA_NODE_RESULTS.md`, `DAYTONA_SCIPY_RESULTS.md` 및 최신 `HACKATHON_HANDOFF.md`가 gate 통과를 기록했다. 원본을 덮어써 과거 상태를 지우지 않고 패키지에 함께 보존한다. [S1][S2][S3][S4][S5]

초기 논의에 있던 `VERIFY` action은 최종 계약의 독립 action이 아니다. 최종 Planner action은 `COMPARE | SEARCH_BOUNDARY | STOP` 세 개이고, 양 끝 재검증은 engine의 책임이다. `size`를 discovered factor로 부르던 이전 표현도 최신 계약에서는 수정됐다. [S1][C1]

### 후보 조사에서 유지할 판단

Node 외에 pandas #66259, ty #3104, FastAPI #15547, Polars #29020, Node #63863 및 #65646, 초기 SciPy #25692를 검토했다. 선정 보고서는 큰 입력과 설치 비용, 불확실한 두 번째 factor, 비결정성, 메모리 압박, 불명확한 버전 경계, 구성 불가능한 패키지 조합 등을 탈락 또는 후순위 사유로 기록한다. 각 사유를 모든 후보에 일괄 적용하는 것은 아니며, 이 후보들을 실제로 모두 실행했다는 뜻도 아니다. Node가 짧은 실행과 분명한 조건 비교에 적합해 주력 fixture가 됐다. [S2]

이전 sandbox 비교 제품과 수상작을 살핀 논의에서는 **병렬 world를 띄우는 장면 자체를 새로움의 전부로 삼지 말자**는 결론을 얻었다. 그래서 fixed matrix로 끝나는 데모보다 증거가 다음 실험을 바꾸는 loop를 출품의 중심에 뒀다. 이는 제품 전략의 판단이며 경쟁 제품보다 성능이 높다거나 수상이 보장된다는 검증 결과는 아니다. [C1]

## 6 검증한 두 데모

### Demo A Node 65601

같은 8바이트 buffer를 multi-byte typed array로 바라보는 작은 코드가 런타임과 생성 방식에 따라 달라진다. fixture는 실제 typed-array 생성 중 발생한 예외를 잡고, 예외가 없으면 PASS 및 exit 0, 예외가 있으면 FAIL 및 exit 1을 낸다. 이는 view 생성 여부를 검사하는 oracle이며 애플리케이션 전체의 정합성을 검사하는 테스트는 아니다. [S2][S4][S9]

조작 변수는 `size`, `allocation=pooled|slow`, `length=implicit|explicit`, `width=8|16|32`다. `slow`는 `Buffer.allocUnsafeSlow`, `pooled`는 `Buffer.allocUnsafe` 경로다. 화면의 “unpooled”와 코드의 `slow`가 같은 개입을 뜻한다. explicit은 `Math.floor(size / BYTES_PER_ELEMENT)` 길이를 명시한다. 따라서 arbitrary size에서 완전히 같은 view 범위를 보장하는 동치 변경으로 설명하지 않는다.

**Daytona Linux x86_64 결과. 각 칸은 독립 Node 프로세스 5회다.** [S4]

| 조건 | 26.7.0 | 26.8.1 | 26.9.0 |
|---|---|---|---|
| 8 B pooled implicit Uint32 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 8 B pooled explicit Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B slow implicit Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B pooled implicit Uint8 | PASS 5/5 | PASS 5/5 | PASS 5/5 |
| 8 B pooled implicit Uint16 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 32767 B pooled implicit Uint32 | PASS 5/5 | FAIL 5/5 | PASS 5/5 |
| 32768 B pooled implicit Uint32 | PASS 5/5 | PASS 5/5 | PASS 5/5 |

3버전 × 7조건 × 5회 = **105/105 일관**. 기본 Linux sandbox에 공식 Node Linux x64 바이너리를 받고 공식 SHA-256 manifest와 대조한 뒤, 변경하지 않은 `repro.js`를 실행했다. 요청한 이름 대신 `process.version`으로 실제 런타임을 확인했다.

8 B 입력의 backingLength는 26.7.0에서 65536, 26.8.1에서 65599, 26.9.0에서 65600이었다. 26.8.1의 FAIL 메시지는 `RangeError: byte length of Uint32Array should be a multiple of 4`다. 32768 B에서는 pool을 우회하며 backing allocation이 32768 B였다. 이 관측은 pool과 view 조건이 관련된다는 해석을 뒷받침하지만 내부 구현 root cause를 이 실험만으로 완전히 규명했다고 주장하지 않는다.

Windows에서는 26.7.0, 26.8.1, 26.8.2, 26.9.0의 7조건을 10회씩 실행해 **280/280** 일관성을 얻었다. 26.8.2 FAIL은 Windows 근거다. Linux gate에 26.8.2는 포함되지 않았다. 발표 화면의 실제 live runtime은 `26.8.1`로 적고, `26.8.x 전체`로 넓히지 않는다. [S2][S4]

정확한 결과 문장은 “Node 26.8.1, pooled 경로, implicit Uint32 조건에서 **관측한 인접 전환은 32767 B FAIL / 32768 B PASS**”다. 더 작은 모든 size, 모든 offset, 모든 multi-byte view를 전수 검증한 것은 아니다. 32768을 최소 실패 크기라고 부르는 것도 방향이 반대다. 이 지점에서는 작은 쪽이 실패하고 큰 쪽이 통과했다.

### Demo B SciPy 24359

동일한 complex symmetric, non-Hermitian 이슈 행렬의 역행렬을 계산하고 `A_inv @ A`가 단위행렬에 가까운지 검사한다. oracle은 `np.allclose(..., rtol=1e-10, atol=1e-10)`이며 오차는 `max(abs(A_inv @ A - I))`다. 예외 유무뿐 아니라 조용히 틀린 계산 결과도 failure로 다룰 수 있다는 사례다. [S5][S6]

**Daytona Linux의 실제 runtime은 Python 3.14.4, NumPy 2.3.5였다.** create 요청에는 `python:3.13-slim`이 들어갔지만 출력은 3.14.4였다. 이를 3.13 실행 결과로 보고하지 않는다.

| SciPy와 조건 | 결과 | 최대 절대 오차 | 반복 |
|---|---|---:|---|
| 1.16.3 이슈 행렬 inv | PASS | 5.57e-16 | 5/5 |
| 1.17.0 이슈 행렬 inv | FAIL | 9.107408 | 5/5 |
| 1.17.1 이슈 행렬 inv | PASS | 7.23e-16 | 5/5 |
| 세 버전 Hermitian control inv | 모두 PASS | 각 1.11e-16 | 각 5/5 |
| 1.17.0 이슈 행렬 solve-auto | FAIL | 9.107408 | 5/5 |
| 1.17.0 이슈 행렬 solve-general | PASS | 5.47e-16 | 5/5 |
| 1.17.0 이슈 행렬 solve-sym | PASS | 7.23e-16 | 5/5 |

총 9조건 × 5회 = **45/45 일관**. Windows에서는 Python 3.13.5 및 NumPy 2.3.5를 고정해 15조건 × 10회 = 150/150을 확인했다. 서로 다른 검증 환경과 조건 집합이므로 같은 실험을 195회 반복했다고 합치지 않는다.

가장 엄밀한 두 번째 factor는 solver assumption이다. 같은 행렬을 유지하고 옵션만 바꾸기 때문이다. Hermitian 대조군은 행렬 계수도 달라져 Hermitian 성질 하나의 효과만을 분리한 실험은 아니다. SciPy는 범주형 대조의 fallback으로 충분하지만 Node와 같은 size 경계를 검증한 사례는 아니다.

### 실행 시간의 단위를 혼동하지 않는다

| 측정 | 결과 | 범위와 한계 |
|---|---|---|
| Node Windows 전체 프로세스 | 중앙값 137 ms | 280회, 로컬 수치 |
| Node Windows oracle 내부 | 중앙값 0.0095 ms | 환경 준비 제외 |
| Node Linux oracle 내부 | 중앙값 0.0031 ms | sandbox lifecycle 제외 |
| Node Linux 5프로세스 case batch | 0.74~0.92 s, 중앙값 0.79 s | 원격 batch 실행 |
| Node Linux 3개 sandbox 병렬 gate | 총 13.54 s | 생성, 바이너리 준비, 각 35프로세스, 삭제 포함 |
| SciPy Linux oracle 명령 왕복 | 중앙값 1.48 s, 1.37~2.48 s | 45개 실행 |
| SciPy Linux 두 버전 병렬 측정 | 총 25.07 s | 각 10회 실행, 의존성 설치와 삭제 포함 |

이 수치들은 특정 측정의 결과다. Planner 호출, 다단계 경계 탐색, UI를 포함한 EnvBisect end-to-end 실행 시간은 아직 측정되지 않았다. [S2][S4][S5]

## 7 제품 입력과 데이터 모델

제품 비전의 입력은 실패한 CI run 링크다. 실제 제품은 저장소와 commit, job, runtime, dependency lockfile, 명령, 로그 및 artifact를 모으고 비교 가능한 known-good를 찾아야 한다. 하지만 해커톤 MVP의 입력은 **수동으로 제공하는 작은 RunBundle**이다. CI ingestion, OAuth, 자동 baseline finder는 미구현이다. 화면에 URL을 보여주더라도 prepared demo input임을 표시한다. [S1][C1]

초기 실패를 Daytona에서 재현하지 못하면 의미 있는 대조를 시작할 수 없다. good가 PASS이고 bad가 FAIL인지 먼저 실행해 확인한다. 외부 상태나 secret, hardware 조건이 빠져 있으면 `Unable to reconstruct` 또는 `INCONCLUSIVE`로 멈춘다.

### 네 종류의 정보를 분리한다

| 구분 | Node 초기 상태 | 의미 |
|---|---|---|
| observed difference | node 26.7.0 → 26.8.1 | 초기 두 입력 및 환경에서 실제 달라진 값 |
| outcome | PASS → FAIL | 결과이며 factor가 아님 |
| available intervention | allocation, length, width, size | fixture가 안전하게 조작할 수 있는 변수 |
| discovered evidence | Round 1 뒤의 backingLength 등 | 실행해서 얻은 값, 직접 조작하지 않음 |

`size=8`은 초기 good/bad 양쪽에서 같다. 처음부터 조작 가능하지만 아직 관련성이 확인된 변수는 아니다. `backingLength`는 raw baseline 로그에 존재할 수 있어도 초기 Planner용 projection의 증거와 factor 목록 전체에서 제외한다. Round 1 이후 실행 증거로 추가하고 `manipulable=false`로 둔다. 이는 CI에 원래 주어진 정보와 실험으로 얻은 정보를 분리하는 계약이다. [S1]

### 최소 신규 계약

`RunBundle`은 `good_world`, `bad_world`, `observed_differences`, `factors`를 갖는다. `Factor`는 `id`, `kind`, `source`, `domain`, `manipulable`을 갖는다. `ExperimentAction`은 `action`, `factor`, `values`, `fixed`, `reason`을 갖는다. 이 세 계약은 설계이며 당일 구현 대상이다.

```yaml
observed_differences:
  - {field: node, good: '26.7.0', bad: '26.8.1'}
factors:
  - {id: node, source: observed, domain: ['26.7.0', '26.8.1']}
  - {id: allocation, source: available_intervention, domain: [pooled, slow]}
  - {id: length, source: available_intervention, domain: [implicit, explicit]}
  - {id: width, source: available_intervention, domain: [8, 16, 32]}
  - {id: size, source: available_intervention, domain: {min: 1, max: 100000}}
```

위는 읽기 위한 축약 예시다. 실제 계약에는 `kind`와 `manipulable` 등 필수 필드를 넣는다. `100000`은 안전한 실행 도메인의 상한이며 정답 경계가 아니다. 파라미터 없는 임의 프로젝트에서 이런 factor를 자동 발견하고 안전한 adapter로 만드는 기능은 미래 과제다.

## 8 Planner와 Engine과 Runner

```text
RunBundle + verified baselines
        |
        v
Planner -> validated ExperimentAction
        |
        v
Experiment Engine -> WorldSpec[]
        |
        v
Daytona Runner -> Observation[]
        |
        v
Evidence projection + world_id join -> Planner
        |
        v
STOP -> evidence package
```

### Planner가 결정하는 것

`COMPARE`는 범주형 개입의 비교를 선택한다. `values`에 완전한 개입 조합을 나열하고 나머지 조건은 `fixed`에 둔다. `SEARCH_BOUNDARY`는 정수형 탐색 축 하나와 seed 및 범위를 선택한다. `STOP`은 현재 증거로 종료한다. action은 정확히 하나만 반환한다.

Planner에는 allowed domains, 현재까지의 관측, 사용한 예산을 준다. `reason`은 관측 ID를 인용하는 짧은 문장이다. 비용이 낮은 범주형 개입으로 선행 조건을 구분한 뒤, 실제 증거가 숫자 축의 관련성을 뒷받침할 때 경계 탐색을 선택한다. 이 정책은 정답 size 또는 Node 전용 순서를 포함하지 않는다.

> Choose the next executable experiment that reduces uncertainty about the failure conditions. Use only allowed factors and domains. Cite the observations supporting the choice. Never treat ERROR as FAIL. Return exactly one action: COMPARE, SEARCH_BOUNDARY, or STOP.

모델이 다른 합리적인 첫 batch를 선택할 수 있다. 문서의 Round 1 네 world는 검증된 예시이며 모델에 강제된 정답 순서로 사용하지 않는다. action의 형식이나 도메인이 잘못됐으면 제한된 repair 또는 STOP으로 처리하고, 실행하지 않은 관측을 만들어 채우지 않는다.

### Engine이 결정하는 것

Engine은 action의 factor와 값, 고정 조건, 예산을 검사하고 실행 가능한 WorldSpec으로 바꾼다. 명령은 adapter 또는 검증된 template에서 구성한다. Planner에게 자유로운 shell 작성을 맡기지 않는다. Engine이 순차 또는 병렬 탐색, 중복 probe cache, 실제 runtime 및 fixture 증거 검증, 경계 재검증을 담당한다.

Round 1 뒤 선택 예시는 다음과 같다. **32767/32768이라는 답은 출력에 없다.** [S1]

```yaml
action: SEARCH_BOUNDARY
factor: size
values: {seed_observed_bad: 8, min: 1, max: 100000}
fixed: {node: '26.8.1', allocation: pooled, length: implicit, width: 32}
reason: 'r1-u32 fails; r1-unpooled, r1-explicit and r1-u8 pass. Probe size under the failing conditions.'
```

예시 reason은 탐색 동기이며 size가 원인임을 이미 입증했다는 뜻은 아니다. size 변경 뒤의 실제 관측이 그 가설을 검증한다.

### 기존 Runner의 정확한 계약

| API 또는 자료형 | 계약과 주의점 |
|---|---|
| Upload | source Path, destination str |
| WorldSpec | 필수 world_id, runtime, command. 선택 image, env, factor_values, timeout_seconds, uploads |
| runtime 및 factor_values | 메타데이터다. 이것만 바꿔도 runtime이 바뀌는 것은 아니다 |
| image 및 command | image가 생성 경로를 선택하며 command가 실제 실행을 결정한다 |
| ExperimentBatch | worlds tuple, max_parallel 기본 4. 허용 1~4 |
| run_one | 하나 생성, 업로드, 실행, 관측, finally에서 삭제 시도 |
| run_batch | thread pool 사용, 반환 순서는 입력 순서 |
| Observation | world_id, status, exit_code, stdout, lifecycle 및 단계별 시간, deleted, evidence, error |

Observation에는 `factor_values`가 없다. Engine은 `world_id`로 원래 WorldSpec과 연결해 Planner 입력을 만든다. `evidence`는 stdout에서 찾은 마지막 JSON object이며 없으면 빈 dict다. 원시 stdout 전체를 기본 prompt로 전달할 필요는 없지만 audit 자료에는 보존한다.

exit 0은 PASS, 그 외는 runner에서 FAIL로 처리한다. fixture JSON의 PASS/FAIL과 exit 판정이 충돌하면 ERROR다. 요청 또는 생성 오류, 삭제 실패도 오류로 다룬다. 키나 `requests`가 없으면 sandbox 생성 전에 `DaytonaUnavailable`이 발생하고 batch에서 전파될 수 있다. 자동 retry는 없다.

**Engine에서 더 엄격히 검사할 항목:** 유효한 exit_code, 필요한 evidence 존재, 실제 runtime, factor 값, `deleted=true`, status와 oracle의 일치. 현재 runner는 exitCode가 누락돼도 0이 아닌 값으로 처리할 수 있으므로, 누락을 행동상의 FAIL로 받아들이면 안 된다. `ERROR`는 실행 기반의 문제이고 제품 진단 결과는 `INCONCLUSIVE`로 표시한다. 기존 Observation status에 INCONCLUSIVE를 새로 끼워 넣는 설계는 아니다. [S7]

기본 command timeout은 30초이고 handoff의 Node 예시는 180초다. HTTP timeout은 create 90초, 파일별 upload 45초, execute는 command timeout+30초, delete 60초다. 이 값들은 3분 무대 제한보다 클 수 있다. live 전체 시간 예산은 별도 engine 및 발표 운영 정책으로 관리해야 한다. thread의 대기를 끝냈다고 원격 실행이 취소되고 삭제됐다고 가정하지 않는다.

### 검증 경로 연결에서 가장 자주 틀릴 부분

Linux gate는 `image=None`인 기본 sandbox에서 `node_prep.py`가 버전 고정 공식 바이너리를 다운로드하고 hash를 검증한 경로였다. 기존 `fixture_adapter.node_world(...)`는 `verified_image`를 요구하며 `node repro.js ...`를 내보낸다. **adapter의 image 경로는 해당 gate에서 검증하지 않았다.** 당일 adapter의 매핑만 연결하거나 handoff 3장의 명시적 WorldSpec을 engine에서 사용한다. [S1][S4]

## 9 Adaptive experiment loop와 경계 탐색

### Round 0 기준 세계를 다시 만든다

같은 fixture와 size=8, pooled, implicit, width=32를 고정하고 26.7.0 PASS 및 26.8.1 FAIL을 확인한다. 두 세계가 비교 가능한지 확인하기 전에는 다음 추론을 진행하지 않는다. CI history만으로 verified 배지를 붙이지 않는다.

### Round 1 실패를 유지하거나 없애는 조건을 비교한다

| world ID | 26.8.1과 size 8을 고정한 개입 | 기존 Linux 관측 |
|---|---|---|
| r1-explicit | pooled, explicit, width 32 | PASS, backingLength 65599 |
| r1-unpooled | slow, implicit, width 32 | PASS, backingLength 8 |
| r1-u8 | pooled, implicit, width 8 | PASS, backingLength 65599 |
| r1-u32 | pooled, implicit, width 32 | FAIL, backingLength 65599 |

위 네 결과가 live에서 나왔을 때 Planner가 그 증거를 받아 다음 action을 고른다. “런타임이 26.8.1이면 항상 실패한다”는 설명은 충분하지 않다. 같은 runtime에서도 개입에 따라 outcome이 달라졌기 때문이다. 화면은 각 결과와 짧은 근거를 보여주고 긴 모델 reasoning을 중심에 놓지 않는다.

### Round 2 size를 선택하고 실행으로 좁힌다

handoff의 기준 의사코드는 실패 seed에서 size를 배수로 키워 PASS를 찾고, FAIL/PASS bracket을 이분 탐색한다. 이때 bracket은 실패점과 통과점으로 묶인 구간이다. 새 probe는 고정 조건을 유지하고 실제 Daytona 실행으로 판정한다. 어느 시점이든 evidence 누락, ERROR, 예산 소진, 결과 뒤집힘 또는 단일 전환 가정에 반하는 관측이 있으면 INCONCLUSIVE다. [S1]

이후 대화에서는 지연을 줄이기 위해 **최대 4개 probe를 한 번에 실행하는 병렬 bracket 탐색**을 제안했다. 이는 구현 및 검증 전인 설계 변경이다. 네 내부 probe는 수학적으로 최대 다섯 하위 구간을 만든다. 구현에서는 “무조건 4등분” 같은 표현보다, 정렬한 관측 중 FAIL과 PASS가 맞닿은 후보 구간을 선택하는 규칙을 명확히 한다. 아직 PASS endpoint가 없으면 먼저 그것을 확보해야 한다.

```text
1. action, fixed conditions, domain, seed FAIL, budget를 검증한다.
2. 새 probe로 같은 고정 조건의 PASS endpoint를 확보한다.
3. bracket 내부에서 중복 없는 probe를 최대 4개 선택한다.
4. 실제 관측을 정렬하고 단일 전환 가정과 일치하는지 검사한다.
5. 가능한 FAIL/PASS 구간을 좁힌다. 모순이나 ERROR이면 중단한다.
6. 인접한 정수 두 점에 도달하면 양 끝을 새 프로세스로 반복 확인한다.
7. fixed, WorldSpecs, Observations, 횟수와 한계를 묶어 반환한다.
```

한 bracket 내부의 single transition을 가정하는 탐색이다. 탐색하지 않은 구간에서 다른 전환이 없다는 것을 증명하지 못한다. 최종 결과는 **observed adjacent bracket**이며 전역 최소 조건 또는 전역 단조성의 증명이 아니다. “Smallest verified condition found”보다 `FAILURE CONDITION VERIFIED`와 `Observed transition`이 덜 모호하다.

### 실행 예산과 화면 숫자

이전 화면 예시의 `12 worlds`, `2 adaptive rounds`, `2~3초 뒤 결과`는 고정 성과가 아니다. world 수와 실행 수는 실제 누적값을 표시한다. 두 개의 고수준 실험 round 안에서도 여러 search batch가 필요하다. 양 끝 5회씩 재검증하면 그 자체로 10개 프로세스가 추가된다.

예를 들어 정수 bracket 폭이 100000이면 이상적인 5구간 축소도 인접값까지 약 8회의 batch가 필요할 수 있다. 이는 복잡도 설명이며 실제 latency 예측이 아니다. 기본 경로의 4개 batch 실측이 11.153초이므로 25초짜리 무대 구간에 전체 탐색이 들어간다고 보장할 수 없다. 준비 snapshot 연결 여부와 관계없이 실제 end-to-end 리허설로 live 범위를 정한다. 원본 boundary 값을 prompt, hidden config, snapshot, fallback 로직에 주입하지 않는다.

## 10 Snapshot 성능과 사용 결정

2026년 9월 19일 KST의 별도 spike는 기본 Linux sandbox에 SHA-256 검증된 Node 26.8.1 바이너리와 변경하지 않은 fixture를 넣고, 중지한 뒤 filesystem snapshot을 만들었다. 답, expected outcome, boundary, Planner 응답을 넣은 snapshot이 아니다. 이름은 `envbisect-node-2681-spike-20260918154602`이며 생성 당시 active였다. 현재도 active라고 단정하지 않는다. [S1][S8]

| 경로 | 1개 생성부터 삭제까지 | 4개 병렬 전체 wall time |
|---|---:|---:|
| 기본 sandbox와 바이너리 준비 | 12.069 s | 11.153 s |
| 준비 snapshot | 6.191 s | 2.614 s |

병렬 측정의 비율은 약 **4.27배**다. snapshot 설정 일회성 총비용은 **36.652초**, 요청 후 active 대기는 **26.541초**였다. 단일 snapshot world의 create 4.908초는 이후 병렬 world들의 create 1.216~1.344초보다 느렸다. 따라서 고정 startup 시간이나 일반적인 4.27배 성능 향상을 보장하지 않는다.

기본 1개, snapshot 1개, 각각의 4개 fan-out을 합친 **10개 probe** 모두 `v26.8.1`, exit 1, FAIL, backingLength 65599의 같은 핵심 8 B 케이스를 냈고 삭제됐다. 전체 fixture matrix나 자동 탐색 경로를 snapshot에서 검증한 결과는 아니다. source sandbox도 삭제됐으며 snapshot 자체는 당시 남겨 뒀다.

warm pool의 생성 요청은 HTTP 404였고 pool은 생성되지 않았다. 공식 문서는 조직별 활성화를 요구한다. 이 계정의 404 원인을 그 하나로 확정하지 않으며 **warm pool latency 실측은 없다**. snapshot과 warm pool은 같은 측정이 아니다. [S8][W2]

당일 사용 결정은 **선택적 fast path**다. 검증된 runner에는 snapshot selector가 없다. 초반에 작은 별도 연결을 검증할 수 있을 때만 사용하고, 안 되면 기본 sandbox와 `node_prep.py` 경로를 쓴다. 이 snapshot은 26.8.1용이므로 26.7.0 baseline이나 26.9.0 repaired world를 같은 runtime처럼 실행해서는 안 된다. 새 경로에서는 실제 버전, 핵심 PASS/FAIL, 삭제 및 경계 endpoint도 다시 확인해야 한다.

## 11 120분 구현계획과 역할

최우선 결과는 **valid action → 실제 실행 → 증거를 받은 다음 action**이다. 기존 fixture 연구를 재개하지 않고 이 연결을 완성한다. UI나 snapshot 최적화가 이 연결의 시간을 가져가면 CLI와 기본 경로를 선택한다. [S1]

| 경과 시간 | 작업 | 완료 조건 | 막혔을 때 |
|---|---|---|---|
| 0~10분 | 접근과 원본 확인, live smoke | 생성, 실행, 삭제 성공과 기존 근거 확보 | 접근 문제면 BLOCKED, 기록 재생으로 정직하게 전환 |
| 10~25분 | contracts와 수동 RunBundle | 잘못된 action 및 domain 거부 | plain dict와 명시적 검증 |
| 25~45분 | COMPARE를 검증 경로에 연결 | 4개 world의 실제 runtime, factor, 삭제 확인 | handoff의 직접 WorldSpec 구성 |
| 45~70분 | Planner 호출과 projection | Round 1 observation ID에 근거한 유효 action | manual 선택으로 표시, AI claim 중단 |
| 70~95분 | 탐색 및 재검증, loop 연결 | 새 probe로 인접 bracket 또는 INCONCLUSIVE | 예산 제한, 정답 삽입 금지 |
| 95~110분 | 결과 흐름과 evidence export | good/bad, Round 1, 다음 축, 결과가 한 화면에서 추적됨 | 구조화된 CLI 출력 |
| 110~120분 | 3분 리허설과 freeze | 실제 실행 시간, 발표 문구, fallback 확정 | Demo B 또는 명시된 recorded evidence |

### 두 명이면 나눌 일

팀원 A는 contracts, Planner, observation projection, 발표에서 설명할 근거 한 줄을 맡는다. 팀원 B는 Engine, 검증 경로 연결, 탐색과 cleanup, evidence export를 맡는다. 첫 10분에 action의 JSON shape와 world_id 규칙을 같이 정하고, 45분에 실측 Round 1 데이터를 연결한다. 95분부터는 함께 리허설한다. 한 명이면 같은 순서로 진행하고 별도 UI는 생략한다.

### 파일별 작업 범위

- 재사용: `models.py`, `daytona_runner.py`, `smoke_test.py`, `node_prep.py`, 검증된 `repro.js`, gate 원시 관측.
- 제한적으로 연결: `fixture_adapter.py`의 runtime 준비 매핑. 어려우면 engine에서 handoff의 WorldSpec 예제를 사용한다.
- 새로 작성: `contracts.py`, `planner.py`, `experiment_engine.py`, `demo.py`, 수동 RunBundle 파일.
- 이후 확장: CI ingestion, baseline 자동 선택, arbitrary repo factor 추출, UI, Add-to-CI, patch 및 PR 생성.

행사 전 준비한 fixture, runner, snapshot, 측정 자료와 행사 중 새로 만든 기능을 구분해 설명한다. 과거 행사에서 기존 작업 사용을 허용했다는 논의는 현재 서울 행사의 확정 규칙으로 대체할 수 없다. 당일 공지에 맞춰 준비물 사용 범위를 확인한다. 문서의 일정은 실제 시각이 아닌 120분의 경과 시간이다.

## 12 세 분 동안 보여줄 네 장면

아래는 **목표 storyboard**다. 실제 실행 시간은 리허설로 확인한다. 2분 40초에 본문을 끝내고 마지막 20초를 지연 여유로 둔다. 모델이 다른 실험을 선택하거나 latency가 길어졌다면 실제 결과를 따라 설명한다. [C1]

### 장면 1 실패 입력과 기준 세계

0:00~0:15에는 EnvBisect와 실패 CI 입력을 보여준다. CI 연동이 없다면 `Prepared demo run`을 표시한다.

> Your CI tells you something broke. EnvBisect asks which conditions made it break.

0:15~0:30에는 Node 26.7.0 PASS와 26.8.1 FAIL을 나란히 둔다. 초기 observed difference는 Node 버전 하나다. 0:30~0:42에는 실제 baseline 재구성 결과를 보여준다.

> We start from one known-good run and one known-bad run, then reconstruct both in Daytona.

### 장면 2 네 개의 대조 실험

0:42~1:05에는 explicit PASS, unpooled PASS, Uint8 PASS, Uint32 FAIL을 카드 또는 CLI 행으로 보여준다. 모두 Node 26.8.1 및 size 8을 유지한다. PASS/FAIL은 관측이 도착한 뒤 표시하고 현재 실행 또는 기록 재생 여부를 구분한다.

> We change one condition at a time. Three counterfactuals recover. One still fails.

### 장면 3 증거가 다음 실험을 바꾼다

1:05~1:25에는 `Evidence → Next experiment`, 선택한 `SEARCH_BOUNDARY: size`, 고정 조건을 크게 보여준다. 근거에는 r1 observation ID를 짧게 연결한다.

> The next experiment is selected from the evidence we just observed. Now we hold the failing conditions fixed and investigate buffer size.

`size`는 이미 허용된 변수였다. “AI가 입력에 없던 변수를 발명했다” 또는 “이 축은 어디에도 미리 정의되지 않았다”는 말을 쓰지 않는다. 자동 선택된 것은 **다음 탐색 행동**이다.

### 장면 4 실제 탐색과 결과 증거

1:25~1:50에는 새 probe 결과와 줄어드는 bracket을 보여준다. 1:50~2:05에는 실제로 확인한 두 endpoint를 크게 표시한다. 2:05~2:20에는 fixed condition과 검증 횟수 및 현재 실행 근거를 보여준다.

> Same runtime, same fixture, adjacent inputs. One fails; one passes.

화면 제목은 `FAILURE CONDITION VERIFIED`, 결과는 `Observed transition: 32767 B FAIL → 32768 B PASS`다. 이번 live에서 양 끝까지 못 갔으면 얻은 구간과 INCONCLUSIVE를 보여주고, 과거 endpoint는 recorded evidence로 따로 설명한다. 26.9.0의 repaired world는 실제로 실행했거나 과거 검증 표시가 있을 때만 추가한다.

2:20~2:40에는 결과를 개발자의 다음 행동에 연결한다.

> CI found the failure. EnvBisect designed the experiments that isolated its conditions.

`Reproduce failing world`, `Export evidence`, `Add regression coverage`는 제품 방향이다. 아직 연결되지 않은 버튼은 future concept 또는 비활성 상태로 표시한다. 데모의 `12 worlds`나 `2 rounds`는 실제 집계값으로 대체한다.

### UI 우선순위

기존 handoff는 CLI 완성을 우선한다. 이후 네 화면 제안은 발표 표현이다. 한 페이지에 네 단계로 나눠도 되고 terminal에서 순서대로 보여줘도 된다. 120분 안에 필요한 것은 **대조 결과, 증거를 인용하는 다음 action, 새 실행의 최종 조건** 세 장면이다. animation, backend server, 가짜 CI parser를 새 핵심 기능보다 앞세우지 않는다.

## 13 발표용 영어 스크립트

아래는 약 2분 30~40초를 목표로 읽을 대본이다. 말하는 속도와 live 대기는 리허설로 맞춘다. 대괄호는 발표 동작이며 읽지 않는다. 자동 loop가 실제로 완성된 경우의 대본이고, 미완성 기능은 해당 문장을 현재 상태에 맞게 바꾼다.

> Your CI tells you something broke. But it often leaves you with another job: finding the conditions that made it break.
>
> You change a runtime, rebuild an environment, try another option, and run the test again. EnvBisect turns that investigation into a repeatable sequence of experiments.
>
> [Show the baseline pair.]
>
> This prepared demo comes from a real Node regression. The same eight-byte input passes on Node 26.7.0 and fails on 26.8.1. We reconstruct both worlds in Daytona before drawing conclusions.
>
> [Run the counterfactual batch.]
>
> Next, we keep the failing runtime and change one condition at a time. Explicit view length passes. Unpooled allocation passes. A one-byte view passes. The original Uint32 view still fails.
>
> The model receives those execution results. Its job is to choose the next useful experiment, using only interventions our engine can execute.
>
> [Show the actual planner action and its observation references.]
>
> Here, the evidence leads it to investigate buffer size while holding the other failing conditions fixed. This is the important step: the previous results change what we test next.
>
> The model chooses the axis. A deterministic engine selects the probes. Daytona runs the new worlds and returns the evidence.
>
> [Show the verified endpoints, or state the actual stopping result.]
>
> At the observed transition, 32,767 bytes fail and 32,768 bytes pass. These are adjacent tested inputs under the same fixed conditions. We verify the endpoints and retain the execution records.
>
> This establishes a failure condition in the tested scope. It does not prove every possible input or the complete implementation root cause.
>
> Engineers can use this evidence to reproduce the problem, guide a fix, and design regression coverage. Our hackathon feature is the loop that turns one round of evidence into the next executable experiment.
>
> The LLM chooses the experiment. Daytona creates the worlds. Execution decides what's true.

발표에서 “최신 회귀”, “몇 초 만에 모든 원인 발견”, “모든 환경에 일반화” 같은 추가 수식은 붙이지 않는다. 실재 이슈 기반의 준비 fixture라는 표현이면 충분하다.

## 14 예상 질문과 짧은 답변

### CI matrix와 무엇이 다른가

“CI에서도 동적 matrix를 구현할 수 있습니다. 저희는 실패 이후에 어떤 실험을 선택하고, 결과를 어떻게 검증하고, 언제 멈출지를 하나의 진단 workflow로 만듭니다.”

> CI can run dynamic matrices. EnvBisect packages the policy that chooses the next experiment from evidence and returns a verified condition.

### coding agent에게 시키면 되는 것 아닌가

“실행 도구를 가진 agent도 할 수 있습니다. 저희는 임의의 디버깅을 실행 가능한 개입, 통제된 비교, 증거 연결, 반복 검증이라는 계약으로 만듭니다.”

> A coding agent can run experiments too. We make the investigation repeatable and auditable, with execution as the acceptance criterion.

### 왜 Daytona가 필요한가

“컨테이너로 직접 만들 수 있습니다. 이번 제품은 새 실험마다 격리 환경 생성, 병렬 실행, 수집, 삭제를 Daytona로 연결했고, 그 위에 실험 선택 로직을 만듭니다.”

> Daytona provides disposable execution worlds through an API, so our application can focus on choosing and validating experiments.

### 이미 답과 변수를 알고 만든 데모 아닌가

“사람은 fixture의 알려진 결과를 가지고 있습니다. Planner에는 허용된 개입과 관측만 주고 경계값은 주지 않습니다. 새 경계는 실제 실행으로 얻어야 합니다. 다만 모델의 사전학습에 이 공개 이슈가 없었다는 보장은 하지 않습니다.”

> The fixture exposes safe interventions. The planner is not given the boundary, and every reported endpoint must come from a new execution.

### size를 정말 새로 발견했나

“size는 처음부터 fixture가 조작할 수 있는 변수였습니다. Round 1 이후 그 변수를 다음 탐색 대상으로 선택한 것입니다. 현재 MVP는 임의 저장소에서 intervention을 자동 추출하지 않습니다.”

### 원인을 찾았나

“테스트한 조건에서의 실패와 복구, 인접 전환을 검증했습니다. 내부 구현 원인에 대한 완전한 증명과는 구분합니다.”

> We verified the failure conditions in the tested scope. The underlying implementation explanation remains a separate claim.

### Node에만 동작하나

“대상은 결정적인 조건부 회귀입니다. SciPy도 다른 oracle과 solver 개입으로 검증했습니다. 하지만 두 fixture가 모든 프로젝트에 대한 자동화를 증명하지는 않습니다. adapter와 oracle을 일반화하는 일이 남아 있습니다.”

### 105개 sandbox를 띄웠나

“아닙니다. Node gate는 세 버전의 세 sandbox에서 105개의 독립 Node 프로세스를 실행했습니다. 제품 runner는 WorldSpec마다 sandbox를 만들지만 gate 측정과 동일한 단위는 아닙니다.”

### 정말 4배 빠른가

“같은 핵심 케이스의 4개 병렬 실행에서 11.153초와 2.614초를 측정했습니다. 일회성 준비는 36.652초였고, 서비스 보장값이나 전체 제품의 속도는 아닙니다.”

### 신뢰할 수 없는 결과가 나오면 어떻게 하나

“ERROR, 재현 실패, 누락된 증거, 반복 결과의 뒤집힘, 탐색 가정의 모순은 INCONCLUSIVE로 종료합니다. 모델 설명으로 빈 증거를 채우지 않습니다.”

### 해커톤 현장에서 새로 만든 것은 무엇인가

“사전 준비는 fixture, runner, gate 및 성능 측정입니다. 현장에서는 RunBundle과 Planner, Experiment Engine을 연결해 관측이 다음 실행을 선택하는 loop를 만듭니다.” 실제 완성한 범위와 일치하도록 답한다.

### 이득과 비용은 검증했나

“실행 latency와 fixture 안정성은 측정했습니다. 개발자 시간 절감, 전체 탐색의 평균 비용, 고객 지불 의사는 아직 측정하지 않았습니다.”

## 15 리스크와 중단 기준

중단 기준은 실패를 숨기기 위한 장치가 아니라 현재 증거로 말할 수 있는 범위를 정한다. 아래 시간 기준은 당일 운영을 위한 제안이며 원본 성능 측정값이 아니다.

| 리스크 | 확인할 징후 | 중단 또는 전환 기준 |
|---|---|---|
| baseline 재현 실패 | good/bad가 기대와 다름 | adaptive diagnosis 중단, context 누락 조사 |
| 실행 오류를 bug로 오판 | ERROR, exit 누락, evidence 불일치 | 해당 probe 무효, INCONCLUSIVE |
| 실제 runtime 불일치 | 라벨과 process.version 등이 다름 | 요청 환경의 결과로 보고하지 않음 |
| cleanup 실패 | deleted=false | 추가 fan-out 중단, 남은 자원 확인 |
| LLM 출력 실패 | 형식 오류, domain 밖 값, 증거 없는 reason | 제한된 repair 후 STOP 또는 manual 표시 |
| 경계 결과 불안정 | endpoint flip, 다중 전환 관측 | single-transition 탐색 중단 |
| snapshot 미연결 | selector 없음, activation 또는 핵심 케이스 미확인 | 초반 검증이 안 되면 기본 경로 |
| 70분까지 Planner 연결 실패 | Round 1 증거를 다음 action에 못 씀 | UI 작업 중단, loop 연결 집중 |
| 95분까지 자동 루프 실패 | 다음 action이 실행으로 이어지지 않음 | adaptive 제품 claim 제외, 현재 prototype 명시 |
| 110분 리허설에서 시간 초과 | 160초 안에 핵심 설명과 결과 제시 어려움 | recorded evidence 또는 짧은 live 부분을 명시 |
| Demo A 조건 붕괴 | runtime 또는 oracle 결과가 안정적이지 않음 | 검증된 Demo B 경로로 전환 |

**제품 가설의 kill criteria:** 충분한 유효 관측을 줘도 다음 실험이 증거에 반응하지 않고 고정 script에 의존한다면 adaptive experiment라는 차별화가 성립하지 않는다. 안전한 intervention과 판정 oracle을 만들 수 없는 프로젝트도 v1 대상에서 제외한다. 두 fixture 밖의 고객 문제에 적용할 때 매번 큰 수동 연구가 필요하다면 제품 확장의 비용 구조를 다시 검토한다.

### 지원하는 문제와 현재 지원하지 않는 문제

타깃은 sandbox에서 재구성 가능하고 결정적 oracle이 있으며, runtime·dependency·config·input처럼 통제 가능한 변수를 가진 실패다. 버전 × workload, dependency × solver option 같은 조합이 예다.

비타깃은 외부 production 상태를 재현할 수 없는 장애, 특정 proprietary hardware가 꼭 필요한 문제, 확률적 race나 flaky failure, 통계적 performance regression, 무제한 저장소의 자동 factor 발견, 모든 root cause 및 자동 patch다. concurrency나 GPU를 미래에 다룰 수 있다는 가능성과 현재 지원은 구분한다.

## 16 해커톤 당일 실행 체크리스트

### 시작 전

- [ ] `sources/`의 최신 handoff, Node 및 SciPy gate 보고서, raw JSON이 열리는지 확인한다.
- [ ] 사전 준비 범위와 당일 새 기능을 적고 행사 공지와 맞춘다.
- [ ] 현재 프로세스에 Daytona 접근이 준비돼 있는지 확인하고 키를 파일이나 발표 화면에 노출하지 않는다.
- [ ] Python `requests`와 Planner 모델 호출 경로를 확인한다.
- [ ] 제공된 smoke를 실제로 실행해 생성, 명령, 삭제까지 확인한다.
- [ ] Node fixture와 준비 helper를 동일 경로로 묶는다. image label 대신 실제 버전을 읽는다.
- [ ] snapshot을 사용할 경우 현재 active 상태와 별도 연결을 확인한다. 불가하면 기본 경로를 선택한다.

### 구현 중

- [ ] 초기 observed difference에 node만 남고 outcome이 factor에 섞이지 않는다.
- [ ] backingLength가 초기 Planner projection과 factor 목록에 들어가지 않는다.
- [ ] action은 세 종류 중 하나이며 값은 허용 domain 안에 있다.
- [ ] Round 1 결과가 world_id로 원래 실행 조건과 연결된다.
- [ ] 다음 action의 reason이 실제 observation ID를 인용한다.
- [ ] 새 probe의 runtime, factor, status, exit_code, evidence, deleted를 검증한다.
- [ ] 실패 endpoint와 통과 endpoint를 새 프로세스에서 반복 검증한다.
- [ ] probe 수, batch 수, elapsed time과 budget을 실제로 집계한다.
- [ ] evidence package에 WorldSpecs, Observations, action history, fixture hash, fixed 조건과 한계를 저장한다.

### 무대 직전

- [ ] 현재 표시가 LIVE, RECORDED, MANUAL 중 무엇인지 분명하다.
- [ ] CLI 또는 네 장면의 흐름이 160초 목표 안에 들어온다.
- [ ] 자동 CI 수집 및 Add-to-CI를 미구현 상태로 표시한다.
- [ ] 26.8.1과 26.8.x, 프로세스 수와 sandbox 수를 혼동하지 않는다.
- [ ] 마지막 문구가 `FAILURE CONDITION VERIFIED`이고 root cause나 global minimum을 주장하지 않는다.
- [ ] fallback의 SciPy 입력, 실제 runtime, 9.107408 오류와 정상 잔차를 바로 설명할 수 있다.
- [ ] 네트워크 지연 때 보여줄 recorded evidence를 별도 표시해 준비한다.
- [ ] 실험 후 남은 sandbox와 cleanup 상태를 확인한다.

패키지의 시작 명령과 화면용 문구는 별도 `EnvBisect_Field_Guide.md`에 모았다. 이 문서 작성 과정에서 새 Daytona 실험을 실행한 것은 아니며, 위 반복 수와 시간은 원본 검증 기록이다.

## 17 문구와 근거를 관리하는 방법

### 유지할 핵심 문구

| 용도 | 문구 |
|---|---|
| 제품 정의 | EnvBisect is an experimental debugger for conditional CI failures. |
| 사용자 문제 | Your CI tells you something broke. EnvBisect asks which conditions made it break. |
| 역할 분담 | The LLM chooses the experiment. Daytona creates the worlds. Execution decides what's true. |
| 적응형 선택 | The next experiment is selected from the evidence we just observed. |
| 결과 제목 | FAILURE CONDITION VERIFIED |
| 결과 범위 | Observed transition under fixed conditions |
| 발표 마무리 | CI found the failure. EnvBisect designed the experiments that isolated its conditions. |
| 결과 활용 | CI found the failure. EnvBisect turned it into evidence you can keep. |

“CI tests the worlds you already thought of. EnvBisect decides which world to test next.”는 짧은 포지셔닝으로 유지할 수 있다. 기술 설명에서는 CI도 동적 실행을 지원한다는 3장의 한계를 함께 설명한다. “Most debugging starts after you can reproduce the bug”라는 초기 문구는 v1이 baseline 재현부터 요구한다는 사실을 가릴 수 있어 기본 소개로 쓰지 않는다.

### 고쳐서 전달할 표현

- `ROOT CAUSE FOUND` → `FAILURE CONDITION VERIFIED`.
- `the global boundary` 또는 `the minimal condition` → 테스트한 고정 조건의 observed adjacent transition.
- `AI discovered a factor that was not provided` → 주어진 intervention 중 다음 탐색 축을 선택.
- `12 worlds executed` → 실제 집계값. 문서 예시는 성과 수치가 아님.
- `Daytona is the only way` → 이번 실행 기반은 Daytona이며 lifecycle과 병렬 실험을 통합.
- `4.27× faster EnvBisect` → 준비 snapshot의 특정 4개 fan-out에서 관측한 비율.
- `Node 26.8.x Linux proven` → Linux 26.8.1, Windows 26.8.1 및 26.8.2를 각각 명시.

### 근거 목록

`sources/`의 원본은 파일 단위 SHA-256 목록으로 보존한다. [C1]은 이전 대화의 제품 방향과 발표 설계이며 실행 증거와 구분한다. 아래 경로는 패키지 루트 기준이다.

- **[S1]** `sources/envbisect-spike/HACKATHON_HANDOFF.md` — 최신 freeze, 실제 API, 신규 계약, policy, 탐색 의사코드, 120분 계획, snapshot 결정. 최신 첨부본과 같은 hash.
- **[S2]** `sources/attachments/RESULTS_uploaded.md` 및 `sources/demo-a-node-buffer/RESULTS.md` — 첨부 시점의 Windows 검증과 이후 갱신된 선정 보고서. Linux 상태의 시점 차이에 주의.
- **[S3]** `sources/envbisect-spike/RESULTS.md` — 초기 접근 BLOCKED 기록. 현재 gate 상태 판단에는 후속 보고서 사용.
- **[S4]** `sources/envbisect-spike/DAYTONA_NODE_RESULTS.md` 및 `daytona_node_26_7_0.json`, `daytona_node_26_8_1.json`, `daytona_node_26_9_0.json` — Linux gate와 원시 관측.
- **[S5]** `sources/envbisect-spike/DAYTONA_SCIPY_RESULTS.md` 및 `daytona_scipy_1_16_3.json`, `daytona_scipy_1_17_0.json`, `daytona_scipy_1_17_1.json` — Linux gate와 실제 runtime.
- **[S6]** `sources/scipy-24359-fixture/RESULTS.md` — Windows 150개 관측. `sources/envbisect-scipy-repro/RESULTS.md`는 보류한 #25692 기록.
- **[S7]** `sources/envbisect-spike/envbisect/models.py`, `daytona_runner.py`, `fixture_adapter.py`, `README.md`, `smoke_test.py` — 구현의 현재 계약.
- **[S8]** `sources/envbisect-spike/snapshot_latency_results.json` — 10개 probe, setup 비용, snapshot과 기본 경로 및 warm pool 404.
- **[S9]** `sources/demo-a-node-buffer/repro.js` 및 runner fixture 사본 — 실제 oracle 코드.
- **[C1]** 이전 ChatGPT 대화 「해커톤 서치」. 관련 발췌는 `sources/conversation_decisions.md`에 보존. 대화의 가설과 예시는 실측으로 사용하지 않는다.
- **[W1]** [Daytona Snapshots](https://www.daytona.io/docs/snapshots/) — filesystem snapshot 및 sandbox 생성 개념. 2026-09-19 확인.
- **[W2]** [Daytona Warm Pools](https://www.daytona.io/docs/en/warm-pools/) — snapshot과 구분되는 warm pool 및 조직 활성화 안내. 2026-09-19 확인.
- **[W3]** [GitHub Actions matrix](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations) — job 출력 기반 동적 matrix. 2026-09-19 확인.

공개 이슈와 관련 링크: [Node #65601](https://github.com/nodejs/node/issues/65601), [Node 수정 PR #65605](https://github.com/nodejs/node/pull/65605), [Node 26.9.0 릴리스](https://nodejs.org/en/blog/release/v26.9.0), [SciPy #24359](https://github.com/scipy/scipy/issues/24359), [SciPy 수정 PR #24367](https://github.com/scipy/scipy/pull/24367). 이 링크는 원본 보고서의 참고 자료이며, 본 문서의 실행 수치 출처는 위의 보존된 관측이다.
