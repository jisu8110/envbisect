# EnvBisect HackSprint implementation handoff

**Scope:** Build the evidence-driven closed loop during the 120-minute hack. Do not resume fixture research. Demo A (Node #65601) passed its Daytona Linux release gate at 105/105 observations; Demo B (SciPy #24359) is locked at 45/45. The existing REST runner is working infrastructure. The 3-minute pitch should show one clear moment: Round 1 evidence changes the *axis* of Round 2, then new Daytona executions reveal a narrow failure condition.

```text
RunBundle → Planner → ExperimentAction → Experiment Engine
          → WorldSpec[] → Daytona Runner → Observation[]
          → Planner → next ExperimentAction
```

## 1. What exists today: exact public contract

Source of truth: `envbisect/models.py`, `envbisect/daytona_runner.py`, `envbisect/fixture_adapter.py`, and `envbisect/smoke_test.py`. These were read for this handoff; the runner and fixture were not changed.

| Existing API | Exact signature / fields | Behavior |
|---|---|---|
| `Upload` | `Upload(source: Path, destination: str)` | Local file to upload to one sandbox. |
| `WorldSpec` | Required: `world_id: str`, `runtime: str`, `command: str`. Optional: `image: str \| None = None`, `env: dict[str,str] = {}`, `factor_values: dict[str,str\|int] = {}`, `timeout_seconds: int = 30`, `uploads: tuple[Upload,...] = ()`. | Immutable dataclass. `runtime` and `factor_values` are **metadata only**. `image` selects a Daytona image when present; `command` actually determines what executes. |
| `ExperimentBatch` | `ExperimentBatch(worlds: tuple[WorldSpec,...], max_parallel: int = 4)` | Maximum accepted parallelism is 1–4. |
| `run_one` | `run_one(spec: WorldSpec) -> Observation` | Creates one sandbox, uploads files, executes one command, parses evidence, then deletes in `finally`. |
| `run_batch` | `run_batch(batch: ExperimentBatch) -> tuple[Observation,...]` | Uses a thread pool; returned tuple preserves input order. |
| `Observation` | `world_id`, `status: PASS\|FAIL\|ERROR`, `exit_code: int\|None`, `stdout`, `duration_seconds`, `create_seconds`, `upload_seconds`, `execute_seconds`, `delete_seconds`, `deleted`, `evidence: dict`, `error: str\|None` | Immutable dataclass. `evidence` is the last JSON object found in stdout; empty dict if none. `duration_seconds` includes the whole lifecycle. |

**Status rules.** Exit 0 becomes PASS; any other exit becomes FAIL. If the fixture's JSON `status` disagrees with the exit code, the observation becomes ERROR. A request/parse/creation error also becomes ERROR. If deletion fails, status becomes ERROR even if execution succeeded; `deleted` stays false. A missing `DAYTONA_API_KEY` or missing Python `requests` raises `DaytonaUnavailable` before a sandbox is created. `run_batch` can propagate that exception; it does not convert it to observations. The REST timeouts are: create 90 s, each upload 45 s, command `spec.timeout_seconds` remotely and that value + 30 s for the HTTP request, delete 60 s. No retry is implemented. The planner must never treat ERROR as a behavioral FAIL.

The existing `Observation` has **no `factor_values` field**. The engine must join it to its originating `WorldSpec` by `world_id` when forming planner input; do not alter the verified runner/model merely to duplicate that metadata.

**Verified deployment path.** The release gate used Daytona's default Linux sandbox (`image=None`), downloaded a version-pinned official Node Linux binary with `node_prep.py`, verified it against the official SHA-256 manifest, and executed the unchanged `repro.js`. `fixture_adapter.node_world(...)` currently requires a `verified_image` and emits `node repro.js ...`; that adapter path was **not** used by the release gate. Do not silently substitute an unverified image tag. Adapt only this mapping on hack day, or construct the verified default-sandbox WorldSpecs below.

## 2. Minimal new model contract (design, not implemented)

These are proposed data shapes for `contracts.py`. Keep the existing `WorldSpec` and `Observation` dataclasses unchanged. A RunBundle is a small manually supplied demo input, not a CI parser.

| Model | Minimum fields | Meaning |
|---|---|---|
| `RunBundle` | `good_world`, `bad_world`, `observed_differences`, `factors` | Good/bad contain a world id, input/environment values, and a measured outcome. `observed_differences` contains **only input/environment conditions that actually differ in the initial good/bad context**. Outcomes and later execution evidence are separate. |
| `Factor` | `id`, `kind`, `source`, `domain`, `manipulable` | `kind`: categorical/integer/boolean. `source`: `observed`, `available_intervention`, or `discovered`. `domain` is allowed values or a safe numeric range. `manipulable=false` means evidence only, never a direct intervention. |
| `ExperimentAction` | `action`, `factor`, `values`, `fixed`, `reason` | `action`: `COMPARE`, `SEARCH_BOUNDARY`, `STOP`. For COMPARE, `factor` may list several changed axes and `values` is a list of complete intervention assignments. For SEARCH_BOUNDARY, `factor` is one integer axis and `values` contains seed/range. For STOP, both may be empty. `fixed` locks all other conditions. `reason` cites specific prior observation ids/results in one short sentence. |

Suggested minimal representation (field names are the contract; implementation may use dataclasses or JSON):

```yaml
run_bundle:
  good_world:
    world_id: baseline-good
    factors: {node: '26.7.0', size: 8, allocation: pooled, length: implicit, width: 32}
    status: PASS
  bad_world:
    world_id: baseline-bad
    factors: {node: '26.8.1', size: 8, allocation: pooled, length: implicit, width: 32}
    status: FAIL
  observed_differences:
    - {field: node, good: '26.7.0', bad: '26.8.1'}
  factors:
    - {id: node, kind: categorical, source: observed, domain: ['26.7.0', '26.8.1'], manipulable: true}
    - {id: allocation, kind: categorical, source: available_intervention, domain: [pooled, slow], manipulable: true}
    - {id: length, kind: categorical, source: available_intervention, domain: [implicit, explicit], manipulable: true}
    - {id: width, kind: categorical, source: available_intervention, domain: [8, 16, 32], manipulable: true}
    - {id: size, kind: integer, source: available_intervention, domain: {min: 1, max: 100000}, manipulable: true}
```

`observed` means a condition actually changed between the initial good/bad contexts; here that is only `node`. `available_intervention` means a condition can be safely changed but has no initial causal evidence; `size` is in this category because both worlds used size 8. `discovered` means new evidence/condition obtained through execution. The broad numeric cap above is an execution safety bound, not a known answer. `backingLength` may exist in a raw baseline Observation for audit, but **must be withheld from the entire initial planner projection, including its factor list**. After Round 1 it can be added as `{id: backingLength, kind: integer, source: discovered, domain: observed_numeric, manipulable: false}`. A factor being listed never forces its exploration order.

## 3. Round 1 WorldSpec examples, using the verified path

These four examples are the experiment batch requested for Demo A. They are **example interventions**, not planner logic or a prescribed order. Each world has the same bad Node runtime and 8-byte input. It uploads the existing helper and unchanged fixture; `node_prep.py` fetches and verifies the official binary in that sandbox. Its command uses the verified binary rather than trusting `WorldSpec.runtime` to select Node.

```python
from pathlib import Path
from models import ExperimentBatch, Upload, WorldSpec

ROOT = Path('outputs/envbisect-spike').resolve()
UPLOADS = (
    Upload(ROOT / 'node_prep.py', 'node_prep.py'),
    Upload(ROOT / 'envbisect/fixtures/node_65601/repro.js', 'repro.js'),
)

def example_world(world_id: str, allocation: str, length: str, width: int) -> WorldSpec:
    factors = dict(node='26.8.1', size=8, allocation=allocation,
                   length=length, width=width)
    return WorldSpec(
        world_id=world_id,
        runtime='node-26.8.1',  # label only
        image=None,             # verified default Daytona Linux path
        uploads=UPLOADS,
        factor_values=factors,
        timeout_seconds=180,
        command=(
            'python3 node_prep.py 26.8.1 && '
            '/tmp/node-fixture repro.js '
            f'--size=8 --allocation={allocation} --length={length} --width={width}'
        ),
    )

round_1 = ExperimentBatch(worlds=(
    example_world('r1-explicit', 'pooled', 'explicit', 32),
    example_world('r1-unpooled', 'slow', 'implicit', 32),
    example_world('r1-u8', 'pooled', 'implicit', 8),
    example_world('r1-u32', 'pooled', 'implicit', 32),
), max_parallel=4)
# observations = run_batch(round_1)
```

For each observation, validate `deleted`, `status`, `exit_code`, `evidence.node == 'v26.8.1'`, and that evidence factors match the WorldSpec. The production planner may choose a different first-round batch. The compiled WorldSpecs should be shown to users as executed facts, not as evidence that the planner followed a hardcoded sequence.

## 4. Planner input after Round 1 (example)

Send a **projection** of each existing `Observation`: `world_id`, factor values from the corresponding WorldSpec, status, exit code, selected JSON evidence (`node`, `backingLength`, `error`, `viewLength`), duration, and cleanup state. Omit full stdout unless needed for an error. The statuses and relevant evidence below match the live Linux gate; durations illustrate the schema rather than claiming exact measurements for these new WorldSpecs.

```yaml
run_bundle: <the good/bad bundle from section 2>
last_action:
  action: COMPARE
  factor: [allocation, length, width]
  values:
    - {allocation: pooled, length: explicit, width: 32}
    - {allocation: slow, length: implicit, width: 32}
    - {allocation: pooled, length: implicit, width: 8}
    - {allocation: pooled, length: implicit, width: 32}
  fixed: {node: '26.8.1', size: 8}
  reason: 'test counterfactuals around the bad world'
observations:
  - world_id: r1-explicit
    factors: {node: '26.8.1', size: 8, allocation: pooled, length: explicit, width: 32}
    status: PASS
    exit_code: 0
    evidence: {node: v26.8.1, backingLength: 65599, error: null}
    duration_seconds: 5.0
    deleted: true
  - world_id: r1-unpooled
    factors: {node: '26.8.1', size: 8, allocation: slow, length: implicit, width: 32}
    status: PASS
    exit_code: 0
    evidence: {node: v26.8.1, backingLength: 8, error: null}
    duration_seconds: 5.0
    deleted: true
  - world_id: r1-u8
    factors: {node: '26.8.1', size: 8, allocation: pooled, length: implicit, width: 8}
    status: PASS
    exit_code: 0
    evidence: {node: v26.8.1, backingLength: 65599, error: null}
    duration_seconds: 5.0
    deleted: true
  - world_id: r1-u32
    factors: {node: '26.8.1', size: 8, allocation: pooled, length: implicit, width: 32}
    status: FAIL
    exit_code: 1
    evidence: {node: v26.8.1, backingLength: 65599, error: 'RangeError: byte length of Uint32Array should be a multiple of 4'}
    duration_seconds: 5.0
    deleted: true
```

Prompt instruction for the hack-day planner: choose **exactly one** next `ExperimentAction` from `COMPARE | SEARCH_BOUNDARY | STOP` using only the RunBundle, allowed factor domains, and observed executions. Cite the observation ids that justify the choice. Return schema-valid data, not prose. **Prefer low-cost categorical interventions that distinguish prerequisite conditions before starting an ordered numeric boundary search. Use SEARCH_BOUNDARY only when prior executable evidence gives a reason to believe the numeric factor is relevant.** This is a generic experimental policy, not a Node-specific sequence. Do not provide expected outcomes, a boundary location, or hidden fixture metadata. A validation failure or an ERROR observation must trigger repair/stop, never be silently counted as FAIL.

## 5. Planner SEARCH_BOUNDARY output (example)

The planner chooses an axis and fixed conditions. It does **not** report a boundary value. The engine discovers any boundary by executing new Daytona worlds.

```yaml
action: SEARCH_BOUNDARY
factor: size
values: {seed_observed_bad: 8, min: 1, max: 100000}
fixed: {node: '26.8.1', allocation: pooled, length: implicit, width: 32}
reason: 'r1-u32 fails while r1-explicit, r1-unpooled, and r1-u8 pass; size may change the backing allocation path, so probe it while holding the failing conditions fixed.'
```

The planner output has no adjacent-size answer. The executor's search range comes from a safe allowed input domain, and its observations are the only source for the resulting bracket.

## 6. Deterministic SEARCH_BOUNDARY engine pseudocode only

```text
input: validated SEARCH_BOUNDARY action, prior observations, probe budget
assert factor is integer, manipulable, and all fixed values are in their domains
seed := action.values.seed_observed_bad
assert a prior PASS/FAIL observation proves seed is FAIL under exactly action.fixed

probe(size):
    compile a WorldSpec using only action.fixed plus size
    run the unchanged fixture through Daytona runner
    verify cleanup, actual runtime, factors, exit/status agreement
    if status is ERROR or evidence is missing: return INCONCLUSIVE
    cache and return PASS or FAIL with the full Observation

bad := seed
candidate := next larger value by doubling, capped at action.values.max
while budget remains and candidate is within domain:
    outcome := probe(candidate)
    if outcome is PASS: good := candidate; break
    if outcome is FAIL: bad := candidate; increase candidate geometrically
    if outcome is INCONCLUSIVE: stop as INCONCLUSIVE
if no PASS found: stop as INCONCLUSIVE (no bracket)

while good - bad > 1 and budget remains:
    mid := floor((bad + good) / 2)
    outcome := probe(mid)
    if outcome is FAIL: bad := mid
    if outcome is PASS: good := mid
    if outcome is INCONCLUSIVE: stop as INCONCLUSIVE

if good - bad != 1: stop as INCONCLUSIVE (budget exhausted)
repeat both endpoints in fresh processes, e.g. five times each
if any flip or cleanup failure: stop as INCONCLUSIVE
return observed adjacent bracket: bad=FAIL, good=PASS,
       fixed conditions, exact WorldSpecs, Observations, and probe count
```

The search assumes a single transition *within the probed bracket*. Never claim global monotonicity or an untested universal minimum. If observations contradict that assumption, return INCONCLUSIVE and let the planner choose another action. Do not patch the fixture to make the search pass.

## 7. File ownership on hack day

| Treatment | Files | Why |
|---|---|---|
| Reuse unchanged | `envbisect/models.py`, `envbisect/daytona_runner.py`, `envbisect/smoke_test.py`, `envbisect/fixtures/node_65601/repro.js`, `node_prep.py`, Daytona release-gate observations | Verified execution substrate and oracle. Keep source and evidence auditable. |
| Modify only to connect the verified runtime path | `envbisect/fixture_adapter.py` | It currently requires an image, while the tested path uses default Daytona Linux plus SHA-verified official Node binary. Preserve factor validation; map runtime selection into upload/prep/command. |
| Create | `envbisect/contracts.py`, `envbisect/planner.py`, `envbisect/experiment_engine.py`, `envbisect/demo.py`, one small static RunBundle input file | New contracts, LLM action selection, deterministic action compilation/search, and the closed-loop CLI presentation. No server or UI. |

The adapter change is a focused connection, not a runner refactor. If it takes too long, construct WorldSpecs exactly as in section 3 inside the experiment engine and leave the adapter untouched. The existing REST runner should remain unmodified.

## 8. 120-minute implementation checklist

| Time | Goal | Files | Done when | Failure fallback |
|---|---|---|---|---|
| 0–10 min | Verify access and freeze working evidence. | `smoke_test.py`, existing reports | One live sandbox is created/executed/deleted; Demo A raw evidence is available. | Diagnose key/network only briefly. If Daytona is unavailable, label the run blocked and use clearly marked recorded evidence for rehearsal; do not claim a live demo. |
| 10–25 min | Add minimal RunBundle/Factor/Action validation and static input. | New `contracts.py`, static RunBundle file | Good/bad facts and allowed domains load; invalid factor/action fails fast. | Use plain dictionaries with explicit checks. Avoid a schema framework. |
| 25–45 min | Compile `COMPARE` to WorldSpecs on the verified Node path. | Focused `fixture_adapter.py` change or new `experiment_engine.py` | A 4-world Round 1 batch runs in Daytona; every Observation has matching factors/runtime and `deleted=true`. | Use the explicit WorldSpec construction from section 3. Do not rewrite the runner. |
| 45–70 min | Add planner call with strict `ExperimentAction` output and observation ids in reason. | New `planner.py` | Given Round 1 evidence, planner returns a valid next axis/action without a supplied boundary answer. | If LLM unavailable, allow an operator-chosen action clearly labeled **manual**; do not present it as AI adaptation. |
| 70–95 min | Implement deterministic boundary engine and close the loop. | New `experiment_engine.py`, `demo.py` | `SEARCH_BOUNDARY` compiles new worlds, returns a verified adjacent bracket or INCONCLUSIVE, and passes resulting evidence back to planner. | Limit probes, keep Round 1 evidence, and report INCONCLUSIVE rather than hardcode or guess a boundary. |
| 95–110 min | Prepare a one-screen terminal narrative. | `demo.py` | Good/Bad → Round 1 evidence → AI-chosen Round 2 axis → executable bracket all visible with source world ids. | Show the same stages as structured terminal output. No UI build. |
| 110–120 min | Rehearse the 3-minute pitch and freeze. | No new feature files | End-to-end run completes; each claim can be pointed to an Observation. | Use Demo B as a clearly labeled fallback fixture if Demo A execution fails; never manufacture missing live evidence. |

**Pitch discipline:** Spend seconds on the Node error, then show the world results changing. The distinctive claim is the evidence-driven choice of a new experiment axis followed by actual isolated execution. The current scaffold already provides the worlds and observations; the hack-day work is the closed loop between them.

## 9. Daytona prepared-snapshot latency spike (2026-09-19 KST)

A one-off snapshot was created from the same default Daytona Linux sandbox path. Before snapshotting, the sandbox contained only the SHA-256-verified official Node **26.8.1** binary and the unchanged `repro.js`. The sandbox was stopped, then a filesystem snapshot was created. No fixture outcome, boundary value, expected status, or planner answer was placed in it. Snapshot name: `envbisect-node-2681-spike-20260918154602`; it was **active** after creation. The source sandbox and all measured child sandboxes were deleted. The snapshot itself remains available for a possible live demo.

| Path | Create | Upload + runtime prep | Execute | Delete | Full create→delete |
|---|---:|---:|---:|---:|---:|
| Default sandbox + `node_prep.py`, one world | 1.61 s | 5.13 + 3.91 s | 0.70 s | 0.73 s | **12.07 s** |
| Prepared snapshot, first world | 4.91 s | 0 s | 0.73 s | 0.55 s | **6.19 s** |
| Default path, four worlds in parallel | 1.04–1.66 s/world | 4.57–5.17 + 3.28–3.63 s/world | 0.76–0.79 s/world | 0.51–0.57 s/world | **11.15 s wall** |
| Prepared snapshot, four worlds in parallel | 1.22–1.34 s/world | 0 s | 0.71–0.76 s/world | 0.52–0.64 s/world | **2.61 s wall** |

The prepared snapshot reduced the measured four-world wall time by about **4.27×**. One-time snapshot setup took **36.65 s**, including base sandbox create/upload/prep, stop, snapshot activation, and base deletion; snapshot activation itself took 26.54 s after the snapshot request. The first snapshot world had a slower create than the later four, so do not promise a fixed speedup. All ten measured probes (one baseline, one snapshot, four baseline fan-out, four snapshot fan-out) produced the same `v26.8.1` fixture FAIL and exit code 1, with `backingLength=65599`; this spike tested the core 8-byte case, not the full fixture matrix. Raw timings are in `snapshot_latency_results.json`.

Warm pool was not available through the current account API: the documented `POST /api/warm-pools` returned HTTP 404. No pool was created. Daytona's [snapshot documentation](https://www.daytona.io/docs/snapshots/) supports filesystem snapshots and sandbox creation from them; [warm pools](https://www.daytona.io/docs/en/warm-pools/) require organization enablement.

**Live-demo decision: optional fast path, never a dependency.** The latency gain is useful for a four-world reveal, and the prepared snapshot is active now. However, the existing `daytona_runner.py` only sends `image` or the default create body; it has **no snapshot selector**. Do not refactor that verified runner during this freeze. On hack day, use the snapshot only if a small separate snapshot dispatch path is connected and live-checked early; otherwise keep the verified default-sandbox + `node_prep.py` path. The adaptive evidence loop takes priority over this optimization. If the snapshot is inactive on event day, reactivate or use the default path without delaying the core build.
