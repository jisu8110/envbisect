# EnvBisect 해커톤 현장 가이드

실행 순서와 발표 문구 · 2026년 9월 19일 KST

## 1 먼저 공유할 세 문장

EnvBisect는 CI 실패 뒤에 사람이 하던 조건 변경과 재실행을, 증거에 따라 다음 실험을 고르는 흐름으로 만든다. Node와 SciPy fixture 및 Daytona runner는 사전 검증됐고, 현장에서 만들 핵심은 **Planner → Engine → 실행 증거 → 다음 Planner action**의 연결이다. 결과는 검증된 실패 조건이며 모든 입력의 최소 조건 또는 내부 구현 root cause를 증명한 것은 아니다.

> The LLM chooses the experiment. Daytona creates the worlds. Execution decides what's true.

## 2 준비된 것과 구현할 것

| 준비 완료 | 당일 구현 |
|---|---|
| Node Linux 105/105 관측 일관 | 수동 RunBundle과 action 검증 |
| SciPy Linux 45/45 관측 일관 | 실제 Planner 호출 및 증거 projection |
| 최대 4개 world의 REST runner | action을 검증된 WorldSpec으로 연결 |
| fixture와 Node 바이너리 준비 helper | 결정적 탐색, endpoint 재검증, evidence export |
| snapshot의 별도 실측 | 선택적 snapshot 연결, 우선순위는 loop |

105/105는 105개 sandbox가 아니다. Node gate는 3개 sandbox 안에서 독립 프로세스 105개를 실행했다. 현재 runner는 WorldSpec마다 sandbox를 생성한다. gate 시간과 제품 전체 시간을 혼동하지 않는다.

## 3 시작 명령과 파일 위치

패키지를 풀고 `sources/envbisect-spike/envbisect` 폴더에서 실행한다. 아래 `python`은 `requests`를 설치한 프로젝트용 Python을 뜻한다. API 키는 기존 인증 방식으로 현재 프로세스의 `DAYTONA_API_KEY`에 준비한다. 키 값을 코드, 문서, 공유 화면에 넣지 않는다.

```powershell
Set-Location .\sources\envbisect-spike\envbisect
python -c "import requests; print('requests ready')"
python smoke_test.py
```

의존성이 없으면 패키지 루트에 별도 환경을 만든다. 새 설치가 필요한 경우에만 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests
.\.venv\Scripts\python.exe sources\envbisect-spike\envbisect\smoke_test.py
```

smoke의 PASS는 접근·명령·삭제 확인이다. Node fixture나 adaptive loop 전체의 통과를 뜻하지 않는다. 접근이 없으면 BLOCKED가 정상적인 출력이다.

기존 helper와 fixture의 위치는 `sources/envbisect-spike/node_prep.py`, `sources/envbisect-spike/envbisect/fixtures/node_65601/repro.js`다. 실제 WorldSpec은 같은 폴더의 `HACKATHON_HANDOFF.md` 3장을 따른다. 원본 예제의 `outputs/envbisect-spike` ROOT는 이 패키지에서는 `sources/envbisect-spike`로 바꾼다. 그 예제는 path를 연결해야 하는 설계 예시다.

runner의 `runtime`은 라벨이다. 실제 실행은 Node 준비 helper와 `/tmp/node-fixture` 명령으로 선택하고 fixture의 `node` 증거로 확인한다. `fixture_adapter.py`의 image 경로는 Linux release gate 경로가 아니었다.

## 4 120분 타이머

| 시간 | 끝나 있어야 하는 일 |
|---|---|
| 0~10 | 접근, smoke, 기존 근거 확인. snapshot 연결은 여기서 짧게 판단 |
| 10~25 | RunBundle, Factor, Action과 domain 검증 |
| 25~45 | 실제 4개 COMPARE world와 일치하는 증거 수집 |
| 45~70 | Round 1 증거를 받아 다음 action을 반환하는 Planner |
| 70~95 | 새 탐색 probe, 경계 또는 INCONCLUSIVE, loop 연결 |
| 95~110 | CLI 또는 네 장면, evidence export |
| 110~120 | 리허설, fallback 확정, 새 기능 중단 |

두 명이면 A는 contracts·Planner·projection, B는 engine·runner 연결·탐색·cleanup을 맡는다. 45분에 실제 관측으로 통합하고 95분부터 같이 리허설한다. UI는 핵심 loop가 연결된 뒤 여유가 있을 때 만든다.

## 5 데이터와 결과를 확인하는 체크리스트

- [ ] 초기 차이는 `node: 26.7.0 → 26.8.1`뿐이다. PASS/FAIL은 outcome이다.
- [ ] size는 available intervention, backingLength는 Round 1 뒤 discovered evidence다.
- [ ] 초기 Planner projection 어디에도 backingLength나 알려진 boundary 답이 없다.
- [ ] action은 COMPARE, SEARCH_BOUNDARY, STOP 중 정확히 하나다.
- [ ] action의 reason이 실제 observation ID를 인용한다.
- [ ] Observation에 factor_values가 없으므로 world_id로 WorldSpec과 연결한다.
- [ ] 실제 runtime, factor, exit_code, evidence, status, deleted를 확인한다.
- [ ] ERROR 및 증거 누락은 FAIL로 계산하지 않는다.
- [ ] endpoint는 고정 조건을 유지하고 새 프로세스로 반복 확인한다.
- [ ] world 수, 프로세스 수, batch 수, 시간은 실제 집계한다.
- [ ] 최종 package에 실행 명세, 관측, action history, fixture hash, 한계를 남긴다.

## 6 발표 중 펼쳐 볼 증거

Node Demo A의 Round 1은 26.8.1과 size 8 고정이다. explicit length, slow allocation, Uint8은 PASS이고 pooled implicit Uint32는 FAIL이다. Linux gate의 관측된 endpoint는 **32767 B FAIL / 32768 B PASS**, 각 5/5다. 26.9.0에서 해당 실패 조건은 PASS였다. Linux에서 26.8.2를 검증했다는 주장은 하지 않는다.

SciPy Demo B는 실제 Linux runtime **Python 3.14.4, NumPy 2.3.5**다. SciPy 1.17.0의 이슈 행렬 inv와 solve-auto는 최대 절대 오차 **9.107408**로 FAIL이다. 1.16.3 및 1.17.1의 inv는 약 1e-15 수준으로 PASS다. 같은 1.17.0과 같은 행렬에서 solve-general 또는 solve-sym은 PASS다. 범주형 대조 fallback이며 size 경계 데모는 아니다.

snapshot 비교는 기본 4개 병렬 **11.153초**, 준비 snapshot 4개 병렬 **2.614초**다. 준비 일회성 비용 **36.652초**, 동일 핵심 케이스의 총 **10개 probe**였으며 모두 삭제됐다. 현재 runner에는 snapshot selector가 없다. 전체 자동 loop의 실행 시간과 warm pool 성능은 아직 측정하지 않았다.

## 7 160초 발표 큐

| 구간 | 보여줄 것 | 영어 문구 |
|---|---|---|
| 0~30초 | prepared CI input, good/bad | Your CI tells you something broke. EnvBisect asks which conditions made it break. |
| 30~42초 | 실제 baseline 확인 | We reconstruct both worlds in Daytona. |
| 42~65초 | 네 대조 결과 | Three counterfactuals recover. One still fails. |
| 65~85초 | 증거를 인용하는 다음 action | The next experiment is selected from the evidence we just observed. |
| 85~125초 | 실제 probe와 endpoint | Same runtime, same fixture, adjacent inputs. One fails; one passes. |
| 125~160초 | 조건과 증거, 제품 가치 | CI found the failure. EnvBisect designed the experiments that isolated its conditions. |

마지막 20초는 지연 여유다. 이 시간표는 목표다. live 탐색이 아직 endpoint에 도달하지 않았으면 그 상태를 보여준다. recorded evidence로 전환할 때 표시하고 설명한다. 최종 화면은 `FAILURE CONDITION VERIFIED` 또는 실제 중단 결과다.

## 8 문제가 생기면

- baseline이 재현되지 않음: 실험 진단을 멈추고 context 부족으로 표시.
- ERROR, exit 누락, 삭제 실패: probe 무효. 추가 실행과 남은 자원 확인.
- Planner 불가: operator 선택을 MANUAL로 표시. AI adaptation이라고 말하지 않음.
- search 예산 소진 또는 결과 뒤집힘: INCONCLUSIVE. 알려진 답으로 채우지 않음.
- snapshot 연결 불가: 검증된 기본 sandbox 경로로 계속.
- Demo A 불안정: 준비한 SciPy Demo B 실행 경로 또는 표시된 기록으로 전환.
- 네트워크 지연: LIVE와 RECORDED를 구분하고 실제 완료된 범위를 설명.

95분까지 자동 loop가 안 되면 adaptive 기능이 완성됐다고 발표하지 않는다. 110분 리허설에서 160초 목표가 안 되면 live 범위를 줄이거나 기록을 명시해 사용한다.

## 9 심사 질문 네 개

**CI matrix 아닌가?** CI도 동적 matrix가 가능하다. 우리의 제품은 관측에서 다음 실험을 고르고 검증된 조건으로 종료하는 진단 workflow다.

**agent도 할 수 있지 않나?** 가능하다. 실험 계약, controlled comparison, 증거와 중단 기준으로 반복 가능한 흐름을 만든다.

**답을 미리 알고 있지 않나?** 사람은 fixture 결과를 알지만 Planner에게 boundary를 주지 않는다. 보고하는 경계는 새 실행에서 얻어야 한다. 모델의 기존 지식이 없다고 보장하지 않는다.

**왜 Daytona인가?** 새 실험의 생성, 병렬 실행, 수집과 삭제를 검증된 API 경로로 연결한다. 다른 인프라로도 만들 수 있지만 이번 제품의 실행 기반은 Daytona다.

전체 근거와 설명은 `EnvBisect_Handoff.md` 및 PDF를 본다. 실제 구현은 `sources/envbisect-spike/HACKATHON_HANDOFF.md`의 계약을 기준으로 한다.
