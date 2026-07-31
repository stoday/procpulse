from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from os import PathLike

from .command import parse_commands
from .display import display as display_processes
from .exceptions import ManagerClosedError, ProcessNotFoundError, ProcessStartError
from .models import StopResult
from .process import ProcessObject


class ProcessManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, ProcessObject] = {}
        self._closed = False

    def run_external_process(
        self,
        command: str | Sequence[str],
        *,
        mode: str = "sequence",
        cwd: str | PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        output_limit: int | None = 10 * 1024 * 1024,
        timeout: float | None = None,
    ) -> list[ProcessObject]:
        with self._lock:
            if self._closed:
                raise ManagerClosedError("ProcessManager is closed")
            if mode not in {"sequence", "parallel"}:
                raise ValueError("mode must be 'sequence' or 'parallel'")
            command_lines = parse_commands(command)
            processes = [
                ProcessObject(
                    command_line,
                    cwd=cwd,
                    env=env,
                    encoding=encoding,
                    errors=errors,
                    output_limit=output_limit,
                    timeout=timeout,
                )
                for command_line in command_lines
            ]
            for process in processes:
                self._processes[process.id] = process

            if mode == "parallel":
                try:
                    for process in processes:
                        process.start()
                except ProcessStartError:
                    for pending in processes:
                        pending.mark_skipped()
                    raise
            else:
                processes[0].start()
                threading.Thread(
                    target=self._run_sequence,
                    args=(processes,),
                    daemon=True,
                ).start()
            return processes

    @staticmethod
    def _run_sequence(processes: list[ProcessObject]) -> None:
        for index, process in enumerate(processes):
            outcome = process.wait()
            if outcome.exit_code != 0:
                for skipped in processes[index + 1 :]:
                    skipped.mark_skipped()
                return
            if index + 1 < len(processes):
                try:
                    processes[index + 1].start()
                except ProcessStartError:
                    for skipped in processes[index + 2 :]:
                        skipped.mark_skipped()
                    return

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
