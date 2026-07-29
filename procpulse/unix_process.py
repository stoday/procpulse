from __future__ import annotations

import os
import signal
from typing import Any

import psutil

from .backend import ProcessBackend

PROCESS_GROUP_ENV = "PROCPULSE_PROCESS_GROUP"


class UnixProcessBackend(ProcessBackend):
    """Process-group operations for Linux and macOS."""

    def __init__(self) -> None:
        self._inherited_group = os.environ.get(PROCESS_GROUP_ENV) == "1"

    def prepare_environment(self, env: dict[str, str] | None) -> dict[str, str]:
        prepared = dict(os.environ) if env is None else dict(env)
        prepared[PROCESS_GROUP_ENV] = "1"
        return prepared

    def popen_options(self) -> dict[str, Any]:
        if self._inherited_group:
            return {}
        return {"start_new_session": True}

    def terminate(self, process: Any) -> None:
        if process.poll() is not None:
            return
        if self._inherited_group:
            self._signal_descendants(process.pid, signal.SIGTERM)
            self._signal_pid(process.pid, signal.SIGTERM)
            return
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

    def kill_tree(self, process: Any) -> bool:
        if self._inherited_group:
            descendants = self._descendants(process.pid)
            for child in reversed(descendants):
                self._signal_pid(child.pid, signal.SIGKILL)
            self._signal_pid(process.pid, signal.SIGKILL)
            return True
        if process.poll() is not None:
            return True
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        return True

    def _descendants(self, pid: int) -> list[psutil.Process]:
        try:
            return psutil.Process(pid).children(recursive=True)
        except psutil.Error:
            return []

    def _signal_descendants(self, pid: int, sig: signal.Signals) -> None:
        for child in reversed(self._descendants(pid)):
            self._signal_pid(child.pid, sig)

    @staticmethod
    def _signal_pid(pid: int, sig: signal.Signals) -> None:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
