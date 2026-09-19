"""Instrumented REST lifecycle. The original verified runner is kept unchanged.

Only lifecycle/observability change: same uploads, command and fixture, plus
cooperative cancellation, attributable sandbox names and server-side expiry.
"""
import os
import time
import requests
from daytona_runner import API, PROXY, _evidence_from_stdout
from models import Observation


def run_one(spec, *, run_id, emit, cancelled):
    started = time.perf_counter()
    sandbox_id = None
    deleted = False
    stdout, exit_code, evidence, error, status = "", None, {}, None, "ERROR"
    timings = dict(create_seconds=None, upload_seconds=None, execute_seconds=None, delete_seconds=None)
    name = f"envbisect-{run_id}-{spec.world_id}"[:120]
    headers = {"Authorization": "Bearer " + os.environ["DAYTONA_API_KEY"]}

    def phase(value, **extra):
        emit("world_phase", {"world_id": spec.world_id, "phase": value, "sandbox_id": sandbox_id,
                             "sandbox_name": name, **extra})

    def check_cancel():
        if cancelled.is_set():
            raise RuntimeError("Cancelled before next lifecycle operation")

    try:
        check_cancel()
        phase("CREATING", ttl_minutes=15)
        t = time.perf_counter()
        body = {"name": name, "labels": {"envbisect-run": run_id}, "ttlMinutes": 15,
                "autoStopInterval": 5, "autoDeleteInterval": 0}
        if spec.image:
            body["image"] = spec.image
        response = requests.post(f"{API}/sandbox", headers=headers, json=body, timeout=90)
        response.raise_for_status()
        created = response.json()
        sandbox_id = created["id"]
        timings["create_seconds"] = time.perf_counter() - t
        phase("CREATED", auto_destroy_at=created.get("autoDestroyAt"))
        # Require acknowledgement of the TTL before starting user-visible work.
        deadline = created.get("autoDestroyAt")
        if not deadline:
            check = requests.get(f"{API}/sandbox/{sandbox_id}", headers=headers, timeout=20)
            check.raise_for_status()
            deadline = check.json().get("autoDestroyAt")
        if not deadline:
            raise RuntimeError("Daytona did not acknowledge sandbox TTL; refusing execution")
        phase("UPLOADING", auto_destroy_at=deadline)
        check_cancel()
        t = time.perf_counter()
        for upload in spec.uploads:
            check_cancel()
            with upload.source.open("rb") as source:
                response = requests.post(f"{PROXY}/{sandbox_id}/files/upload", headers=headers,
                                         params={"path": upload.destination},
                                         files={"file": (upload.source.name, source)}, timeout=45)
            response.raise_for_status()
        timings["upload_seconds"] = time.perf_counter() - t
        check_cancel()
        phase("EXECUTING")
        t = time.perf_counter()
        response = requests.post(f"{PROXY}/{sandbox_id}/process/execute", headers=headers,
                                 json={"command": spec.command, "timeout": spec.timeout_seconds, "envs": spec.env},
                                 timeout=spec.timeout_seconds + 30)
        response.raise_for_status()
        timings["execute_seconds"] = time.perf_counter() - t
        result = response.json()
        stdout, exit_code = result.get("result", ""), result.get("exitCode")
        evidence = _evidence_from_stdout(stdout)
        status = "PASS" if exit_code == 0 else "FAIL"
        phase("OBSERVED", observed_status=evidence.get("status"))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        phase("ERROR", error=error)
    finally:
        if sandbox_id:
            t = time.perf_counter()
            phase("CLEANING")
            try:
                response = requests.delete(f"{API}/sandbox/{sandbox_id}", headers=headers, timeout=60)
                if response.status_code != 404:
                    response.raise_for_status()
                deleted = True
                phase("DESTROYED")
            except Exception as exc:
                status = "ERROR"
                error = f"{error or ''}; cleanup failed: {type(exc).__name__}: {exc}"
                phase("CLEANUP_FAILED", error=error)
            timings["delete_seconds"] = time.perf_counter() - t
        else:
            phase("NOT_CREATED_OR_UNCONFIRMED", cancelled=cancelled.is_set())
    return Observation(spec.world_id, status, exit_code, stdout, time.perf_counter() - started,
                       deleted=deleted, evidence=evidence, error=error, **timings)
