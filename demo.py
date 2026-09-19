"""EnvBisect CLI: actual evidence -> planner -> fresh experiments -> evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
import signal
import threading
from config import ROOT, load_env, redact
from contracts import load_bundle
from engine import Engine, Inconclusive, Cancelled
from executor import NodeExecutor
from planner import OpenAIPlanner, RulesPlanner


class Audit:
    def __init__(self, path, callback=None):
        self.path = path
        self.lock = threading.RLock()
        self.callback = callback
        path.mkdir(parents=True, exist_ok=False)

    def __call__(self, event, data):
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, "data": data}
        encoded = redact(json.dumps(record, ensure_ascii=False, default=str))
        with self.lock:
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
            if self.callback:
                self.callback(json.loads(encoded))

    def summary(self, data):
        temporary = self.path / "summary.tmp"
        temporary.write_text(redact(json.dumps(data, ensure_ascii=False, indent=2, default=str)), encoding="utf-8")
        temporary.replace(self.path / "summary.json")


def log(message):
    print(redact(message), flush=True)


def check_access(model):
    import requests
    checks = [("Daytona", "https://app.daytona.io/api/sandbox", "DAYTONA_API_KEY"),
              ("OpenAI", "https://api.openai.com/v1/models/" + model, "OPENAI_API_KEY")]
    okay = True
    for label, url, key in checks:
        if not os.environ.get(key):
            log(f"{label}: missing {key}")
            okay = False
            continue
        response = requests.get(url, headers={"Authorization": "Bearer " + os.environ[key]}, timeout=20)
        log(f"{label}: HTTP {response.status_code}")
        okay &= response.status_code == 200
    log("Access check only; generation billing/quota and sandbox execution are not tested.")
    return 0 if okay else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["daytona", "local"], help="Default Daytona; --reproduce inherits saved backend")
    parser.add_argument("--planner", choices=["openai", "rules"], default="openai")
    parser.add_argument("--model", help="Overrides OPENAI_MODEL; default gpt-5.5")
    parser.add_argument("--node-dir", type=Path, help="Local mode: root containing version/node.exe (or node)")
    parser.add_argument("--check", action="store_true", help="Read-only API access check; no sandbox or generation")
    parser.add_argument("--smoke", action="store_true", help="Run only two live baseline worlds; no planner call")
    parser.add_argument("--reproduce", metavar="RUN_ID", help="Re-execute one validated world from a saved run")
    parser.add_argument("--world", metavar="WORLD_ID", help="Saved world ID for --reproduce")
    parser.add_argument("--max-worlds", type=int, default=80)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--seconds", type=int, default=900, help="Soft wall-time budget; in-flight cleanup may overrun")
    parser.add_argument("--parallel", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args(argv)
    if args.max_worlds < 2 or args.max_rounds < 1 or args.seconds < 1:
        parser.error("Need at least 2 worlds, 1 round and 1 second")
    try:
        load_env()
        model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5.5"
        if args.check:
            return check_access(model)
        bundle = load_bundle()
        if args.reproduce:
            from history import reproduction
            args.reproduction = reproduction(args.reproduce, args.world)
            args.smoke = True
            args.backend = args.backend or args.reproduction["backend"]
            args.node_dir = args.node_dir or args.reproduction.get("local_node_dir")
        args.backend = args.backend or "daytona"
        executor = NodeExecutor(args.backend, args.node_dir)
        if args.planner == "openai" and not args.smoke and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is missing; set it in .env")
    except Exception as exc:
        log(f"Setup failed: {exc}")
        return 2
    cancelled = threading.Event()
    def interrupt(signum, frame):
        cancelled.set()
        log("Stop requested. Waiting for in-flight calls and sandbox cleanup; do not close this terminal.")
    previous = signal.signal(signal.SIGINT, interrupt)
    try:
        return execute(args, bundle, executor, model, cancelled=cancelled)
    finally:
        signal.signal(signal.SIGINT, previous)


def execute(args, bundle, executor, model, *, run_id=None, cancelled=None, on_event=None):
    cancelled = cancelled or threading.Event()
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    audit = Audit(ROOT / "runs" / run_id, on_event)
    executor.emit, executor.cancelled, executor.run_id = audit, cancelled, run_id
    metadata = {"backend": args.backend, "planner": args.planner, "model": model if args.planner == "openai" else None,
                "fixture_sha256": hashlib.sha256((ROOT / "fixtures" / "repro.js").read_bytes()).hexdigest(),
                "limits": {"max_worlds": args.max_worlds, "max_rounds": args.max_rounds, "seconds": args.seconds, "parallel": args.parallel},
                "execution": "LIVE", "local_platform": sys.platform,
                "isolation": "fresh Daytona Linux sandbox" if args.backend == "daytona" else "fresh local process + temporary directory; NOT sandboxed",
                "reproduction": getattr(args, "reproduction", None), "smoke": args.smoke,
                "source_issue_url": getattr(args, "issue_url", None),
                "local_node_dir": str(executor.node_dir) if executor.node_dir else None,
                "ttl_minutes": 15 if args.backend == "daytona" else None}
    audit("run_started", {**metadata, "bundle": bundle})
    engine = Engine(bundle, executor, audit, log, args.max_worlds, args.seconds, args.parallel, cancelled)
    planner = OpenAIPlanner(bundle, model, audit) if args.planner == "openai" and not args.smoke else RulesPlanner(bundle)
    status, error, closed = "INCONCLUSIVE", None, False
    mode = "MANUAL / NO LLM" if args.smoke else f"OPENAI ({model})" if args.planner == "openai" else "RULES -- NOT AI"
    log(f"\nEnvBisect | LIVE {args.backend.upper()} | planner={mode}")
    log("Expected: creating the typed-array view finishes without an exception.")
    log("Input: supplied good/bad conditions (not a CI-link importer).")
    log(f"Budget: {args.max_worlds} worlds / {args.seconds}s / {args.parallel} parallel. No automatic retries.")
    log(f"Audit: {audit.path}\n")
    try:
        log("1. Reproduce the supplied good/bad condition")
        if getattr(args, "reproduction", None):
            r = args.reproduction
            rows = engine.run([r["factors"]], "reproduce")
            if rows[0]["status"] != r["expected_status"]:
                raise Inconclusive("Reproduced world differs from the saved outcome")
            status = "REPRODUCED"
        else:
            engine.baseline()
        if getattr(args, "reproduction", None):
            pass
        elif args.smoke:
            status = "BASELINE_VERIFIED"
        else:
            for round_number in range(1, args.max_rounds + 1):
                engine.check_cancel()
                if engine.remaining() <= 0:
                    raise Inconclusive("Wall-time budget exhausted before planner call")
                log(f"\n2. Planner round {round_number}: choosing from measured evidence...")
                audit("planner_waiting", {"round": round_number, "planner": args.planner})
                action = planner.choose(engine.state(), timeout=max(1, min(120, engine.remaining())))
                engine.check_cancel()
                if engine.remaining() <= 0:
                    raise Inconclusive("Wall-time budget exhausted during planner call")
                log(f"   {action['action']} | factor={action['factor']}")
                log(f"   Why: {action['reason']}")
                engine.execute(action)
                if action["action"] == "STOP":
                    closed = True
                    status = "VERIFIED_FAILURE_CONDITION" if engine.boundary else "INCONCLUSIVE"
                    if not engine.boundary:
                        error = "Planner stopped without a verified adjacent boundary; compare evidence remains available."
                    break
            else:
                raise Inconclusive("Planner round budget exhausted without STOP")
    except Cancelled as exc:
        status, error = "CANCELLED", str(exc)
    except KeyboardInterrupt:
        status = "CANCELLED"
        error = "Interrupted by user; inspect audit and Daytona dashboard for cleanup state."
    except Exception as exc:
        error = redact(f"{type(exc).__name__}: {exc}")
    elapsed = round(time.monotonic() - engine.started, 3)
    summary = {**metadata, "status": status, "error": error, "planner_closed_loop": closed,
               "worlds_submitted": engine.worlds, "valid_observations": len(engine.rows), "batches": engine.batches,
               "planner_calls": planner.calls, "elapsed_seconds": elapsed, "boundary": engine.boundary,
               "actions": engine.actions, "observations": engine.rows}
    audit("run_finished", {k: v for k, v in summary.items() if k not in ("actions", "observations")})
    audit.summary(summary)
    log(f"\n3. Result: {status}")
    if engine.boundary:
        b = engine.boundary
        log(f"   {b['factor']}={b['fail']} FAIL / {b['factor']}={b['pass']} PASS; each confirmed 5 fresh times.")
        log(f"   Fixed: {b['fixed']}")
        log("   This is a verified failure condition, NOT a root-cause claim or an automatic fix.")
    if error:
        log(f"   {error}")
    log(f"   {engine.worlds} worlds, {engine.batches} batches, {planner.calls} planner calls, {elapsed}s")
    log(f"   Results: {audit.path / 'summary.json'}")
    return 0 if status in ("VERIFIED_FAILURE_CONDITION", "BASELINE_VERIFIED", "REPRODUCED") else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
