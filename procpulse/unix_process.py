from __future__ import annotations

import os
import signal
from typing import Any

from .backend import ProcessBackend


class UnixProcessBackend(ProcessBackend):
    """Process-group operations for Linux and macOS."""

    def popen_options(self) -> dict[str, Any]:
        return {"start_new_session": True}

    def terminate(self, process: Any) -> None:
        if process.poll() is not None:
            return
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)

    def kill_tree(self, process: Any) -> bool:
        if process.poll() is not None:
            return True
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        return True
