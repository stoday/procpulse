from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def default_state_dir() -> Path:
    return Path(os.environ.get("PROCPULSE_HOME", Path.home() / ".procpulse"))


@dataclass
class ProcessRecord:
    id: str
    cmd: list[str]
    work_dir: str
    stdout_path: str
    stderr_path: str
    state: str = "starting"
    pid: int | None = None
    monitor_pid: int | None = None
    exit_code: int | None = None
    termination_reason: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    stop_requested: bool = False
    grace_period: float = 2.0
    stop_reason: str = "cancelled"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessRecord":
        return cls(**data)


class ProcessStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_state_dir()
        self.records_dir = self.root / "records"
        self.output_dir = self.root / "output"

    def create(self, cmd: list[str], work_dir: str) -> ProcessRecord:
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        process_id = str(uuid.uuid4())
        record = ProcessRecord(
            id=process_id,
            cmd=cmd,
            work_dir=work_dir,
            stdout_path=str(self.output_dir / f"{process_id}.stdout"),
            stderr_path=str(self.output_dir / f"{process_id}.stderr"),
        )
        self.save(record)
        return record

    def path(self, process_id: str) -> Path:
        return self.records_dir / f"{process_id}.json"

    def load(self, process_id: str) -> ProcessRecord:
        with self.path(process_id).open(encoding="utf-8") as handle:
            return ProcessRecord.from_dict(json.load(handle))

    def save(self, record: ProcessRecord) -> None:
        self.records_dir.mkdir(parents=True, exist_ok=True)
        target = self.path(record.id)
        fd, temporary = tempfile.mkstemp(prefix=f".{record.id}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self) -> list[ProcessRecord]:
        if not self.records_dir.exists():
            return []
        records: list[ProcessRecord] = []
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as handle:
                    records.append(ProcessRecord.from_dict(json.load(handle)))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return records
