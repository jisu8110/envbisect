"""Read only attributable run artifacts; never expose arbitrary project files."""
import json
import re
import hashlib
from config import ROOT


def run_path(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", run_id):
        raise ValueError("Invalid run ID")
    return ROOT / "runs" / run_id


def read_events(run_id):
    path = run_path(run_id) / "events.jsonl"
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # writer may still be completing the final record
    return records


def read_summary(run_id):
    path = run_path(run_id) / "summary.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def reproduction(run_id, world_id):
    summary = read_summary(run_id)
    if not summary:
        raise ValueError("Reproduction requires a completed recorded run")
    row = next((o for o in summary.get("observations", []) if o["world_id"] == world_id), None)
    if not row:
        raise ValueError("No validated observation for this world")
    if summary.get("fixture_sha256") != hashlib.sha256((ROOT / "fixtures" / "repro.js").read_bytes()).hexdigest():
        raise ValueError("The fixture differs from the recorded run; reproduction is not exact")
    return {"source_run": run_id, "source_world": world_id, "factors": row["factors"], "expected_status": row["status"],
            "backend": summary["backend"], "local_node_dir": summary.get("local_node_dir")}
