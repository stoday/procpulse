from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TerminationReason(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    channel: str
    text: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class ProcessStatus:
    state: str
    is_alive: bool
    pid: int | None
    uptime: float
    return_code: int | None
    cmd: tuple[str, ...]
    work_dir: str


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    stdout: str
    stderr: str
    exit_code: int | None
    duration: float
    termination_reason: TerminationReason
    output_truncated: bool


@dataclass(frozen=True, slots=True)
class StopResult:
    process_id: str
    graceful: bool
    force_killed: bool
    tree_clean: bool
