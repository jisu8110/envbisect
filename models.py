"""The small contract between an experiment planner and world execution."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Status = Literal["PASS", "FAIL", "ERROR"]


@dataclass(frozen=True)
class Upload:
    source: Path
    destination: str


@dataclass(frozen=True)
class WorldSpec:
    world_id: str
    runtime: str
    command: str
    image: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    factor_values: dict[str, str | int] = field(default_factory=dict)
    timeout_seconds: int = 30
    uploads: tuple[Upload, ...] = ()


@dataclass(frozen=True)
class Observation:
    world_id: str
    status: Status
    exit_code: int | None
    stdout: str
    duration_seconds: float
    create_seconds: float | None = None
    upload_seconds: float | None = None
    execute_seconds: float | None = None
    delete_seconds: float | None = None
    deleted: bool = False
    evidence: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ExperimentBatch:
    worlds: tuple[WorldSpec, ...]
    max_parallel: int = 4
