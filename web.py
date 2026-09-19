"""Loopback-only experiment workspace. Browser refresh never starts a run."""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import uuid
from config import ROOT, load_env, redact
from contracts import load_bundle, validate_assignment
from demo import execute
from executor import NodeExecutor
from history import read_events, read_summary, reproduction, run_path

VISIBLE_EVENTS = {"run_started", "worlds_submitted", "world_phase", "world_completed", "observations",
                  "planner_waiting", "action", "search_bracket", "verified_boundary", "run_finished"}


class RunManager:
    def __init__(self, node_dir=None):
        self.node_dir = node_dir
        self.lock = threading.RLock()
        self.worker = None
        self.active_id = None
        self.cancelled = threading.Event()
        self.accepting = True

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self, options):
        if not isinstance(options, dict) or set(options) - {"backend", "planner", "max_worlds", "seconds", "smoke", "source_run", "source_world"}:
            raise ValueError("Unsupported run options")
        with self.lock:
            if not self.accepting:
                raise RuntimeError("Server is shutting down")
            if self.running():
                raise RuntimeError("An experiment is already running; stop it before starting another")
            backend, planner = options.get("backend", "daytona"), options.get("planner", "openai")
            if backend not in {"daytona", "local"} or planner not in {"openai", "rules"}:
                raise ValueError("Unsupported backend or planner")
            worlds, seconds = options.get("max_worlds", 80), options.get("seconds", 900)
            if type(worlds) is not int or not 2 <= worlds <= 100 or type(seconds) is not int or not 30 <= seconds <= 1800:
                raise ValueError("Use 2..100 worlds and 30..1800 seconds")
            if type(options.get("smoke", False)) is not bool:
                raise ValueError("smoke must be boolean")
            if bool(options.get("source_run")) != bool(options.get("source_world")):
                raise ValueError("Reproduction requires both source_run and source_world")
            args = SimpleNamespace(backend=backend, planner=planner, max_worlds=worlds, seconds=seconds,
                                   max_rounds=6, parallel=4, smoke=options.get("smoke", False), reproduction=None)
            if options.get("source_run"):
                args.reproduction = reproduction(options["source_run"], options.get("source_world"))
                validate_assignment(args.reproduction["factors"], load_bundle())
                args.smoke = True
            executor = NodeExecutor(backend, self.node_dir)
            if planner == "openai" and not args.smoke and not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is missing")
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            self.active_id, self.cancelled = run_id, threading.Event()
            def work():
                try:
                    execute(args, load_bundle(), executor, os.getenv("OPENAI_MODEL") or "gpt-5.5",
                            run_id=run_id, cancelled=self.cancelled)
                except Exception as exc:
                    # Preserve a visible failure even for a setup/disk exception outside the run loop.
                    path = run_path(run_id)
                    path.mkdir(parents=True, exist_ok=True)
                    (path / "summary.json").write_text(json.dumps({"status": "ERROR", "error": redact(exc),
                                                                   "backend": backend, "planner": planner}), encoding="utf-8")
            self.worker = threading.Thread(target=work, name=f"run-{run_id}", daemon=False)
            self.worker.start()
            return run_id

    def stop(self, run_id):
        with self.lock:
            if self.running() and run_id != self.active_id:
                raise ValueError("This is not the active run")
            if self.running():
                self.cancelled.set()

    def shutdown(self):
        with self.lock:
            self.accepting = False
            self.cancelled.set()

    def state(self, run_id):
        path = run_path(run_id)
        with self.lock:
            active = self.running() and self.active_id == run_id
            stopping = active and self.cancelled.is_set()
        if not path.exists() and not active:
            raise FileNotFoundError("Run not found")
        events = [e for e in read_events(run_id) if e.get("event") in VISIBLE_EVENTS]
        summary = read_summary(run_id)
        status = "STOPPING" if stopping else "RUNNING" if active else (summary or {}).get("status", "UNATTACHED")
        return {"run_id": run_id, "active": active, "status": status, "events": events, "summary": summary,
                "mode": "LIVE" if active else "RECORDED"}

    def history(self):
        parent = ROOT / "runs"
        result = []
        if not parent.exists():
            return result
        for path in sorted(parent.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            try:
                run_path(path.name)
            except ValueError:
                continue
            summary = read_summary(path.name) or {}
            active = self.running() and path.name == self.active_id
            result.append({"id": path.name, "status": "RUNNING" if active else summary.get("status", "UNATTACHED"),
                           "planner": summary.get("planner"), "backend": summary.get("backend")})
            if len(result) == 60:
                break
        return result


def handler_for(manager, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, status, body, mime="application/json; charset=utf-8", download=False):
            if not isinstance(body, bytes):
                body = redact(json.dumps(body, ensure_ascii=False, default=str)).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="envbisect-evidence.json"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def allowed_host(self):
            port = self.server.server_address[1]
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Loopback Host required"})
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            try:
                static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
                if parsed.path in static:
                    name = static[parsed.path]
                    mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name]
                    return self.send(200, (ROOT / "web" / name).read_bytes(), mime)
                if parsed.path == "/api/status":
                    return self.send(200, {"csrf": token, "active_id": manager.active_id if manager.running() else None,
                        "history": manager.history(), "local_available": bool(manager.node_dir), "local_node_dir": str(manager.node_dir) if manager.node_dir else None,
                        "keys": {k: bool(os.getenv(k)) for k in ("DAYTONA_API_KEY", "OPENAI_API_KEY")},
                        "model": os.getenv("OPENAI_MODEL") or "gpt-5.5"})
                if parsed.path == "/api/run":
                    return self.send(200, manager.state(query.get("id", [""])[0]))
                if parsed.path == "/api/evidence":
                    run_id = query.get("id", [""])[0]
                    state = manager.state(run_id)
                    return self.send(200, {"run_id": run_id, "summary": state["summary"], "events": read_events(run_id),
                                           "fixture": (ROOT / "fixtures" / "repro.js").read_text(encoding="utf-8"),
                                           "runtime_preparation": (ROOT / "node_prep.py").read_text(encoding="utf-8")}, download=True)
                self.send(404, {"error": "Not found"})
            except (ValueError, FileNotFoundError) as exc:
                self.send(404, {"error": str(exc)})

        def do_POST(self):
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if not self.allowed_host() or origin not in allowed_origins or not secrets.compare_digest(self.headers.get("X-EnvBisect-Token", ""), token):
                return self.send(403, {"error": "Same-origin request with session token required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("A small JSON request is required")
                options = json.loads(self.rfile.read(length))
                if self.path == "/api/start":
                    return self.send(202, {"run_id": manager.start(options)})
                if self.path == "/api/stop":
                    if not isinstance(options, dict):
                        raise ValueError("Invalid stop request")
                    manager.stop(options.get("run_id"))
                    return self.send(202, {"status": "STOPPING"})
                self.send(404, {"error": "Not found"})
            except (ValueError, FileNotFoundError) as exc:
                self.send(400, {"error": str(exc)})
            except RuntimeError as exc:
                self.send(409, {"error": str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--node-dir", type=Path, help="Enable local execution with preinstalled pinned Node binaries")
    args = parser.parse_args()
    load_env()
    manager = RunManager(args.node_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(manager, secrets.token_urlsafe(32)))
    stopping = threading.Event()
    def stop(signum, frame):
        if not stopping.is_set():
            print("Stopping server: no new runs. Waiting for current run and sandbox cleanup...", flush=True)
            stopping.set()
            manager.shutdown()
    previous = signal.signal(signal.SIGINT, stop)
    server.timeout = 0.4
    print(f"EnvBisect web: http://127.0.0.1:{args.port}\nUI edits: Ctrl+F5. Python edits: Ctrl+C, wait, then restart this command.\nRefresh/closing a browser tab does NOT stop the run. Use the Stop button.", flush=True)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        if manager.worker:
            manager.worker.join()
        server.server_close()
        signal.signal(signal.SIGINT, previous)
        print("Server stopped. Check run evidence for any cleanup failures.", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
