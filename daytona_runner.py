"""Execute independent WorldSpecs through Daytona's documented REST API."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import time

from models import ExperimentBatch, Observation, WorldSpec


API = "https://app.daytona.io/api"
PROXY = "https://proxy.app.daytona.io/toolbox"


class DaytonaUnavailable(RuntimeError):
    pass


def _require_access() -> str:
    key = os.getenv("DAYTONA_API_KEY")
    if not key:
        raise DaytonaUnavailable("DAYTONA_API_KEY is absent.")
    return key


def _evidence_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def run_one(spec: WorldSpec) -> Observation:
    """Create, upload, execute, observe, and delete one disposable sandbox."""
    key = _require_access()
    try:
        import requests
    except ImportError as exc:
        raise DaytonaUnavailable("Python requests is absent in this project environment.") from exc

    headers = {"Authorization": f"Bearer {key}"}
    started = time.perf_counter()
    sandbox_id = None
    create_s = upload_s = execute_s = delete_s = None
    stdout = ""
    exit_code = None
    error = None
    status = "ERROR"
    deleted = False
    evidence = {}
    try:
        t = time.perf_counter()
        body = {"image": spec.image} if spec.image else {}
        response = requests.post(f"{API}/sandbox", headers=headers, json=body, timeout=90)
        response.raise_for_status()
        sandbox_id = response.json()["id"]
        create_s = time.perf_counter() - t

        t = time.perf_counter()
        for upload in spec.uploads:
            with upload.source.open("rb") as source:
                response = requests.post(
                    f"{PROXY}/{sandbox_id}/files/upload", headers=headers,
                    params={"path": upload.destination},
                    files={"file": (upload.source.name, source)}, timeout=45,
                )
            response.raise_for_status()
        upload_s = time.perf_counter() - t

        t = time.perf_counter()
        response = requests.post(
            f"{PROXY}/{sandbox_id}/process/execute", headers=headers,
            json={"command": spec.command, "timeout": spec.timeout_seconds,
                  "envs": spec.env},
            timeout=spec.timeout_seconds + 30,
        )
        response.raise_for_status()
        execute_s = time.perf_counter() - t
        result = response.json()
        stdout = result.get("result", "")
        exit_code = result.get("exitCode")
        status = "PASS" if exit_code == 0 else "FAIL"
        evidence = _evidence_from_stdout(stdout)
        if evidence.get("status") in ("PASS", "FAIL") and evidence["status"] != status:
            status = "ERROR"
            error = "Fixture status disagrees with process exit code."
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        evidence = _evidence_from_stdout(stdout)
    finally:
        if sandbox_id:
            t = time.perf_counter()
            try:
                response = requests.delete(
                    f"{API}/sandbox/{sandbox_id}", headers=headers, timeout=60)
                response.raise_for_status()
                deleted = True
            except Exception as exc:
                status = "ERROR"
                detail = f"cleanup failed: {type(exc).__name__}: {exc}"
                error = f"{error}; {detail}" if error else detail
            delete_s = time.perf_counter() - t

    return Observation(
        world_id=spec.world_id, status=status, exit_code=exit_code, stdout=stdout,
        duration_seconds=time.perf_counter() - started,
        create_seconds=create_s, upload_seconds=upload_s,
        execute_seconds=execute_s, delete_seconds=delete_s,
        deleted=deleted, evidence=evidence, error=error,
    )


def run_batch(batch: ExperimentBatch) -> tuple[Observation, ...]:
    """Run up to four worlds concurrently and return input-ordered results."""
    _require_access()
    if not 1 <= batch.max_parallel <= 4:
        raise ValueError("max_parallel must be between 1 and 4")
    with ThreadPoolExecutor(max_workers=batch.max_parallel) as pool:
        return tuple(pool.map(run_one, batch.worlds))
