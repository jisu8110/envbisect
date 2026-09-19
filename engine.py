"""Deterministic execution, evidence validation, bounded search and confirmation."""
from dataclasses import asdict
import time
import threading
from contracts import InvalidAction, projection, validate_action, validate_assignment
from models import ExperimentBatch


class Inconclusive(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def check_observation(spec, observation):
    if observation.world_id != spec.world_id:
        raise Inconclusive("Observation world_id does not match its submitted world")
    if observation.status not in ("PASS", "FAIL") or observation.error or not observation.deleted:
        raise Inconclusive(f"{spec.world_id}: infrastructure/cleanup error: {observation.error or observation.status}")
    evidence = observation.evidence
    if observation.exit_code not in (0, 1) or type(observation.exit_code) is not int:
        raise Inconclusive(f"{spec.world_id}: missing or unexpected process exit code")
    expected = "PASS" if observation.exit_code == 0 else "FAIL"
    if observation.status != expected or evidence.get("status") != expected:
        raise Inconclusive(f"{spec.world_id}: exit/status/evidence disagreement")
    if evidence.get("node") != "v" + spec.factor_values["node"]:
        raise Inconclusive(f"{spec.world_id}: actual runtime does not match requested runtime")
    for key in ("size", "allocation", "length", "width"):
        if type(evidence.get(key)) is not type(spec.factor_values[key]) or evidence[key] != spec.factor_values[key]:
            raise Inconclusive(f"{spec.world_id}: actual factor {key} does not match")
    if type(evidence.get("backingLength")) is not int or evidence["backingLength"] < spec.factor_values["size"]:
        raise Inconclusive(f"{spec.world_id}: missing/invalid backing allocation evidence")
    if expected == "FAIL" and not isinstance(evidence.get("error"), str):
        raise Inconclusive(f"{spec.world_id}: FAIL lacks a fixture error")
    if expected == "PASS" and (evidence.get("error") is not None or type(evidence.get("viewLength")) is not int):
        raise Inconclusive(f"{spec.world_id}: PASS lacks successful view evidence")


class Engine:
    def __init__(self, bundle, executor, audit, log=print, max_worlds=80, seconds=900, parallel=4, cancelled=None):
        self.bundle, self.executor, self.audit, self.log = bundle, executor, audit, log
        self.max_worlds, self.seconds, self.parallel = max_worlds, seconds, parallel
        self.started = time.monotonic()
        self.rows, self.actions = [], []
        self.worlds = self.batches = self.serial = 0
        self.boundary = None
        self.cancelled = cancelled or threading.Event()

    def check_cancel(self):
        if self.cancelled.is_set():
            raise Cancelled("Stopped by user; no new experiments will be submitted")

    def remaining(self):
        return self.seconds - (time.monotonic() - self.started)

    def run(self, assignments, label, ids=None):
        self.check_cancel()
        if self.remaining() <= 0 or self.worlds + len(assignments) > self.max_worlds:
            raise Inconclusive("Execution budget exhausted before new experiments")
        for values in assignments:
            validate_assignment(values, self.bundle)
        specs = []
        for i, factors in enumerate(assignments):
            self.serial += 1
            specs.append(self.executor.world(ids[i] if ids else f"{label}-{self.serial:03d}", factors))
        self.worlds += len(specs)
        self.batches += 1
        self.audit("worlds_submitted", {"label": label, "based_on": self.bundle["bad_world"]["world_id"],
                                        "worlds": [asdict(s) for s in specs]})
        self.log(f"  [{label}] executing {len(specs)} fresh world(s)...")
        observations = self.executor.run_batch(ExperimentBatch(tuple(specs), self.parallel))
        self.audit("observations", {"label": label, "observations": [asdict(o) for o in observations]})
        if len(observations) != len(specs):
            raise Inconclusive("Runner returned an unexpected observation count")
        result, failures = [], []
        for spec, observation in zip(specs, observations):
            try:
                check_observation(spec, observation)
            except Inconclusive as exc:
                failures.append(str(exc))
                continue
            row = asdict(observation)
            row["factors"] = dict(spec.factor_values)
            self.rows.append(row)
            result.append(row)
            f = spec.factor_values
            self.log(f"    {spec.world_id}: {observation.status:4} | Node {f['node']} | size={f['size']} "
                     f"{f['allocation']}/{f['length']}/u{f['width']} | backing={observation.evidence['backingLength']} "
                     f"| cleaned={observation.deleted}")
        self.check_cancel()
        if failures:
            raise Inconclusive("; ".join(failures))
        if self.remaining() <= 0:
            raise Inconclusive("Wall-time budget exceeded; in-flight worlds were allowed to finish cleanup")
        return result

    def baseline(self):
        contexts = [self.bundle["good_world"], self.bundle["bad_world"]]
        rows = self.run([c["factors"] for c in contexts], "baseline", [c["world_id"] for c in contexts])
        for context, row in zip(contexts, rows):
            if row["status"] != context["status"]:
                raise Inconclusive("Live baseline does not reproduce the supplied good/bad context")

    def state(self):
        return {**projection(self.bundle, self.rows, len(self.actions), self.boundary),
                "previous_actions": self.actions,
                "budget": {"worlds_left": self.max_worlds - self.worlds, "seconds_left": round(self.remaining())}}

    def execute(self, action):
        self.check_cancel()
        validate_action(action, self.bundle, self.rows)
        # The first real intervention must precede an adaptive numeric search.
        if action["action"] == "SEARCH_BOUNDARY" and not self.actions:
            raise InvalidAction("Run a controlled comparison before numeric boundary search")
        self.audit("action", action)
        if action["action"] == "COMPARE":
            self.run([{**action["fixed"], **v} for v in action["values"]], f"round{len(self.actions) + 1}")
        elif action["action"] == "SEARCH_BOUNDARY":
            self.boundary = self.search(action)
            self.audit("verified_boundary", self.boundary)
        self.actions.append(action)

    def search(self, action):
        axis, fixed, values = action["factor"], action["fixed"], action["values"]
        tested = {}

        def ingest(rows):
            for row in rows:
                if {k: v for k, v in row["factors"].items() if k != axis} != fixed:
                    continue
                size, status = row["factors"][axis], row["status"]
                if not values["min"] <= size <= values["max"]:
                    continue
                if size in tested and tested[size] != status:
                    raise Inconclusive("Repeated observation flipped outcome")
                tested[size] = status
            ordered = sorted(tested)
            seen_pass = False
            for size in ordered:
                if tested[size] == "PASS":
                    seen_pass = True
                elif seen_pass:
                    raise Inconclusive("Observed outcomes contradict the single FAIL-to-PASS transition assumption")

        def probe(sizes, label):
            rows = self.run([{**fixed, axis: size} for size in sizes], label)
            ingest(rows)
            return rows

        ingest(self.rows)
        bad = values["seed_observed_bad"]
        upper = values["max"]
        good = None
        while good is None:
            candidates = []
            next_size = bad
            for _ in range(self.parallel):
                next_size = min(upper, max(next_size + 1, next_size * 2))
                if next_size > bad and next_size not in candidates:
                    candidates.append(next_size)
                if next_size == upper:
                    break
            if not candidates:
                raise Inconclusive("No PASS bracket within the allowed search range")
            probe(candidates, "expand")
            passing = [size for size in tested if size > bad and tested[size] == "PASS"]
            if passing:
                good = min(passing)
                bad = max(size for size in tested if size < good and tested[size] == "FAIL")
            else:
                bad = max(candidates)
                if bad == upper:
                    raise Inconclusive("No PASS bracket within the allowed search range")
        while good - bad > 1:
            self.audit("search_bracket", {"factor": axis, "fail": bad, "pass": good, "fixed": fixed,
                                          "assumption": "single FAIL-to-PASS transition within probed bracket"})
            # Up to four equally spaced probes reduce a bracket to one observed interval.
            candidates = sorted({bad + (good - bad) * i // (self.parallel + 1)
                                 for i in range(1, self.parallel + 1)} - {bad, good})
            probe(candidates, "narrow")
            good = min(size for size in tested if size > bad and tested[size] == "PASS")
            bad = max(size for size in tested if size < good and tested[size] == "FAIL")
        endpoint_ids = []
        self.audit("search_bracket", {"factor": axis, "fail": bad, "pass": good, "fixed": fixed, "confirming": True})
        endpoints = [bad, good] * 5
        # Each repeat is a fresh process (and a fresh sandbox in Daytona mode).
        for offset in range(0, len(endpoints), self.parallel):
            rows = probe(endpoints[offset:offset + self.parallel], "confirm")
            endpoint_ids.extend(r["world_id"] for r in rows)
        return {"status": "VERIFIED_FAILURE_CONDITION", "factor": axis, "fail": bad, "pass": good,
                "fixed": fixed, "fresh_repeats_per_endpoint": 5, "confirmation_world_ids": endpoint_ids,
                "scope": "Observed adjacent FAIL/PASS under fixed conditions; not root cause, global monotonicity, or a universal minimum."}
