"""Strict boundaries between untrusted planner choices and executable worlds."""
import copy
import json
from config import ROOT


class InvalidAction(ValueError):
    pass


def load_bundle():
    return json.loads((ROOT / "bundle.json").read_text(encoding="utf-8"))


def factors_by_id(bundle):
    return {f["id"]: f for f in bundle["factors"] if f["manipulable"]}


def validate_assignment(values, bundle, complete=True):
    domains = factors_by_id(bundle)
    if not isinstance(values, dict) or not set(values) <= set(domains):
        raise InvalidAction("Unknown or non-manipulable factor")
    if complete and set(values) != set(domains):
        raise InvalidAction("Every world must specify all manipulable factors")
    for name, value in values.items():
        factor = domains[name]
        domain = factor["domain"]
        if factor["kind"] == "integer":
            valid = type(value) is int and domain["min"] <= value <= domain["max"]
        else:
            valid = any(type(value) is type(v) and value == v for v in domain)
        if not valid:
            raise InvalidAction(f"Out-of-domain value for {name}")


def validate_action(action, bundle, observations):
    if not isinstance(action, dict) or set(action) != {"action", "factor", "values", "fixed", "reason"}:
        raise InvalidAction("Action must have exactly action/factor/values/fixed/reason")
    reason = action["reason"]
    if not isinstance(reason, str) or not 1 <= len(reason) <= 2000:
        raise InvalidAction("A short evidence-based reason is required")
    if not any(o["world_id"] in reason for o in observations):
        raise InvalidAction("reason must cite a prior world_id")
    if not any(status in reason for status in ("PASS", "FAIL")):
        raise InvalidAction("reason must cite PASS/FAIL evidence, not just an id")
    kind, axis, values, fixed = (action[k] for k in ("action", "factor", "values", "fixed"))
    validate_assignment(fixed, bundle, complete=False)
    if kind == "STOP":
        if axis or values or fixed:
            raise InvalidAction("STOP must have empty factor, values and fixed")
        return
    domains = factors_by_id(bundle)
    if kind == "COMPARE":
        if not isinstance(axis, list) or not axis or not all(isinstance(a, str) for a in axis):
            raise InvalidAction("COMPARE factor must be a nonempty list")
        if len(set(axis)) != len(axis) or set(axis) & set(fixed) or set(axis) | set(fixed) != set(domains):
            raise InvalidAction("factor and fixed must partition all manipulable factors")
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise InvalidAction("COMPARE needs 1..4 worlds")
        for row in values:
            if not isinstance(row, dict) or set(row) != set(axis):
                raise InvalidAction("Each comparison must assign every changed axis")
            validate_assignment({**fixed, **row}, bundle)
    elif kind == "SEARCH_BOUNDARY":
        if not isinstance(axis, str) or axis not in domains or domains[axis]["kind"] != "integer":
            raise InvalidAction("SEARCH_BOUNDARY requires one manipulable integer factor")
        if set(fixed) != set(domains) - {axis}:
            raise InvalidAction("SEARCH_BOUNDARY must fix every other factor")
        if not isinstance(values, dict) or set(values) != {"seed_observed_bad", "min", "max"}:
            raise InvalidAction("SEARCH_BOUNDARY needs seed_observed_bad/min/max")
        low, seed, high = (values[k] for k in ("min", "seed_observed_bad", "max"))
        domain = domains[axis]["domain"]
        if not all(type(v) is int for v in (low, seed, high)) or not domain["min"] <= low <= seed < high <= domain["max"]:
            raise InvalidAction("Invalid search range or seed")
        if not any(o["status"] == "FAIL" and o["factors"] == {**fixed, axis: seed} for o in observations):
            raise InvalidAction("Search seed must be a measured FAIL under exactly fixed conditions")
    else:
        raise InvalidAction("Unknown action")


def projection(bundle, rows, action_count, boundary=None):
    """Baseline backing allocation is audit-only until an intervention has run."""
    projected_bundle = copy.deepcopy(bundle)
    output = []
    for row in rows:
        evidence_keys = ["node", "error", "viewLength"]
        if action_count:
            evidence_keys.append("backingLength")
        output.append({k: copy.deepcopy(row[k]) for k in ("world_id", "factors", "status", "exit_code", "duration_seconds", "deleted")})
        output[-1]["evidence"] = {k: row["evidence"][k] for k in evidence_keys if k in row["evidence"]}
    if action_count:
        observed = sorted({r["evidence"]["backingLength"] for r in rows if "backingLength" in r["evidence"]})
        projected_bundle["factors"].append({"id": "backingLength", "kind": "integer", "source": "discovered", "domain": observed, "manipulable": False})
    return {"run_bundle": projected_bundle, "observations": output, "verified_boundary": boundary}
