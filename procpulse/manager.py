from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from os import PathLike

from .display import display as display_processes
from .exceptions import ManagerClosedError, ProcessNotFoundError
from .models import StopResult
from .process import ProcessObject


class ProcessManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, ProcessObject] = {}
        self._closed = False

    def run_external_process(
        self,
        command: str | PathLike[str],
        args: Sequence[str] | None = None,
        *,
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        output_limit: int | None = 10 * 1024 * 1024,
        timeout: float | None = None,
    ) -> ProcessObject:
        with self._lock:
            if self._closed:
                raise ManagerClosedError("ProcessManager is closed")
            process = ProcessObject(
                command,
                args,
                cwd=cwd,
                env=env,
                encoding=encoding,
                errors=errors,
                output_limit=output_limit,
                timeout=timeout,
            )
            self._processes[process.id] = process
            return process

    def list(self, filter: str | None = None) -> list[ProcessObject]:
        with self._lock:
            processes = list(self._processes.values())
        if filter is None:
            return processes
        return [process for process in processes if process.status.state == filter]

    def stop(self, process_id: str, grace_period: float = 2.0) -> StopResult:
        with self._lock:
            try:
                process = self._processes[process_id]
            except KeyError as exc:
                raise ProcessNotFoundError(process_id) from exc
        return process.stop(grace_period)

    def display(self, processes: Sequence[ProcessObject] | None = None, *, status_interval: float = 0.5) -> None:
        """Display events and status for managed processes until they finish."""
        if processes is None:
            processes = self.list()
        else:
            managed_ids = {process.id for process in self.list()}
            unmanaged = [process.id for process in processes if process.id not in managed_ids]
            if unmanaged:
                raise ProcessNotFoundError(f"Processes are not managed by this manager: {unmanaged}")
        display_processes(processes, status_interval=status_interval)

    def close(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            processes = list(self._processes.values())
        if wait:
            for process in processes:
                process.wait()


def build() -> ProcessManager:
    return ProcessManager()
