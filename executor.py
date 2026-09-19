"""Map validated factors onto the unchanged verified fixture and REST runner."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import tempfile
import time
import threading
import daytona_runner
from config import ROOT
from models import ExperimentBatch, Observation, Upload, WorldSpec


class NodeExecutor:
    def __init__(self, backend="daytona", node_dir=None):
        self.backend = backend
        self.node_dir = Path(node_dir).resolve() if node_dir else None
        self.emit = lambda *args: None
        self.cancelled = threading.Event()
        self.run_id = "standalone"
        if backend == "daytona" and not os.environ.get("DAYTONA_API_KEY"):
            raise RuntimeError("DAYTONA_API_KEY is missing; set it in .env")
        if backend == "local" and not self.node_dir:
            raise RuntimeError("Local backend needs --node-dir with <version>/node.exe (or node)")

    def argv(self, factors):
        binary = self.node_dir / factors["node"] / ("node.exe" if os.name == "nt" else "node")
        if not binary.is_file():
            raise RuntimeError(f"Pinned Node binary not found: {binary}")
        return [str(binary), str(ROOT / "fixtures" / "repro.js"),
                *[f"--{key}={factors[key]}" for key in ("size", "allocation", "length", "width")]]

    def world(self, world_id, factors):
        command = (f"python3 node_prep.py {factors['node']} && /tmp/node-fixture repro.js "
                   + " ".join(f"--{k}={factors[k]}" for k in ("size", "allocation", "length", "width")))
        world = WorldSpec(world_id=world_id, runtime="node-" + factors["node"], command=command,
                          factor_values=dict(factors), timeout_seconds=180,
                          uploads=(Upload(ROOT / "node_prep.py", "node_prep.py"),
                                   Upload(ROOT / "fixtures" / "repro.js", "repro.js")))
        if self.backend == "local":
            world = replace(world, command=subprocess.list2cmdline(self.argv(factors)), uploads=(), timeout_seconds=20)
        return world

    def local_one(self, spec):
        started = time.perf_counter()
        stdout, exit_code, error, evidence, status, deleted = "", None, None, {}, "ERROR", False
        try:
            # Do not give subprocesses the API keys or the caller's environment wholesale.
            env = {k: v for k, v in os.environ.items() if k.upper() in
                   {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "TMPDIR"}}
            with tempfile.TemporaryDirectory(prefix="envbisect-world-") as directory:
                result = subprocess.run(self.argv(spec.factor_values), cwd=directory, env=env,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                                        timeout=spec.timeout_seconds, shell=False)
                stdout, exit_code = result.stdout, result.returncode
                evidence = daytona_runner._evidence_from_stdout(stdout)
                status = "PASS" if exit_code == 0 else "FAIL"
            deleted = True  # local temporary working directory, not a sandbox
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        return Observation(spec.world_id, status, exit_code, stdout, time.perf_counter() - started,
                           deleted=deleted, evidence=evidence, error=error)

    def run_batch(self, batch):
        def run(spec):
            from dataclasses import asdict
            from engine import check_observation
            if self.backend == "daytona":
                from managed_runner import run_one
                observation = run_one(spec, run_id=self.run_id, emit=self.emit, cancelled=self.cancelled)
            else:
                self.emit("world_phase", {"world_id": spec.world_id, "phase": "EXECUTING_LOCAL"})
                observation = self.local_one(spec)
            try:
                check_observation(spec, observation)
                valid, detail = True, None
            except Exception as exc:
                valid, detail = False, str(exc)
            self.emit("world_completed", {"world_id": spec.world_id, "valid": valid, "validation_error": detail,
                                          "observation": asdict(observation)})
            return observation
        with ThreadPoolExecutor(max_workers=batch.max_parallel) as pool:
            return tuple(pool.map(run, batch.worlds))
