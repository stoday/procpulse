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

    def to_string(self) -> str:
        """Return a human-readable multi-line representation of the outcome."""
        return "\n".join(
            [
                "ProcessOutcome:",
                f"  termination_reason: {self.termination_reason.value}",
                f"  exit_code: {self.exit_code}",
                f"  duration: {self.duration:.3f}s",
                f"  output_truncated: {self.output_truncated}",
                "  stdout:",
                _format_output(self.stdout),
                "  stderr:",
                _format_output(self.stderr),
            ]
        )

    def __str__(self) -> str:
        return self.to_string()


def _format_output(output: str) -> str:
    if not output:
        return "    (empty)"
    return "\n".join(f"    {line}" for line in output.rstrip("\n").split("\n"))


@dataclass(frozen=True, slots=True)
class StopResult:
    process_id: str
    graceful: bool
    force_killed: bool
    tree_clean: bool
