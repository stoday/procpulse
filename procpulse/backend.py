from __future__ import annotations

import os
from typing import Any


class ProcessBackend:
    """Platform-specific process-group lifecycle operations."""

    def popen_options(self) -> dict[str, Any]:
        return {}

    def prepare_environment(self, env: dict[str, str] | None) -> dict[str, str] | None:
        return env

    def attach(self, pid: int) -> None:
        del pid

    def terminate(self, process: Any) -> None:
        raise NotImplementedError

    def kill_tree(self, process: Any) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


def create_backend() -> ProcessBackend:
    if os.name == "nt":
        from .windows_process import WindowsProcessBackend

        return WindowsProcessBackend()

    from .unix_process import UnixProcessBackend

    return UnixProcessBackend()
