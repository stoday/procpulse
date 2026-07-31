from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .backend import create_backend
from .exceptions import ProcessStartError
from .models import (
    ProcessOutcome,
    ProcessStatus,
    StopResult,
    StreamEvent,
    TerminationReason,
)

_END = object()


class ProcessObject:
    def __init__(
        self,
        command_line: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        output_limit: int | None = 10 * 1024 * 1024,
        timeout: float | None = None,
    ) -> None:
        if not command_line:
            raise ValueError("command must not be empty")
        self.id = str(uuid.uuid4())
        self._command_line = tuple(command_line)
        self._cmd = tuple(command_line)
        self._queue: queue.Queue[StreamEvent | object] = queue.Queue()
        self._lock = threading.RLock()
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._finished = threading.Event()
        self._outcome: ProcessOutcome | None = None
        self._state = "pending"
        self._termination_reason: TerminationReason | None = None
        self._output_limit = output_limit
        self._buffers = {"stdout": [], "stderr": []}
        self._buffer_sizes = {"stdout": 0, "stderr": 0}
        self._output_truncated = False
        self._encoding = encoding
        self._errors = errors
        self._backend = create_backend()
        self._work_dir = os.path.abspath(os.fspath(cwd)) if cwd is not None else os.getcwd()
        self._cwd = cwd
        self._env = env
        self._timeout = timeout
        self._popen: subprocess.Popen[str] | None = None
        self._reader_threads: list[threading.Thread] = []

    @property
    def status(self) -> ProcessStatus:
        with self._lock:
            now = time.monotonic()
            ended_at = self._finished_at or now
            started_at = self._started_at or now
            return ProcessStatus(
                state=self._state,
                is_alive=self._popen is not None and self._popen.poll() is None,
                pid=self._popen.pid if self._popen is not None else None,
                uptime=ended_at - started_at,
                return_code=self._popen.poll() if self._popen is not None else None,
                cmd=self._cmd,
                work_dir=self._work_dir,
            )

    @property
    def stream(self) -> Iterator[StreamEvent]:
        while True:
            item = self._queue.get()
            if item is _END:
                return
            yield item

    @property
    def outcome(self) -> ProcessOutcome | None:
        with self._lock:
            return self._outcome

    def wait(self, timeout: float | None = None) -> ProcessOutcome:
        if not self._finished.wait(timeout):
            raise TimeoutError("Process did not finish before the timeout")
        assert self._outcome is not None
        return self._outcome

    def start(self) -> None:
        with self._lock:
            if self._state != "pending":
                return
            self._started_at = time.monotonic()
            popen_options: dict[str, Any] = {
                "args": list(self._command_line),
                "cwd": self._cwd,
                "env": self._backend.prepare_environment(dict(self._env) if self._env is not None else None),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": self._encoding,
                "errors": self._errors,
                "bufsize": 1,
                "shell": False,
            }
            popen_options.update(self._backend.popen_options())
            try:
                self._popen = subprocess.Popen(**popen_options)
            except (OSError, ValueError) as exc:
                self._backend.close()
                self._started_at = None
                self._state = "failed"
                self._finished_at = time.monotonic()
                self._termination_reason = TerminationReason.FAILED
                self._outcome = ProcessOutcome(
                    stdout="",
                    stderr=str(exc),
                    exit_code=None,
                    duration=0.0,
                    termination_reason=TerminationReason.FAILED,
                    output_truncated=False,
                )
                self._finished.set()
                self._queue.put(_END)
                raise ProcessStartError(f"Unable to start {list(self._command_line)!r}: {exc}") from exc
            self._backend.attach(self._popen.pid)
            self._state = "running"
            self._reader_threads = [
                threading.Thread(target=self._read_output, args=("stdout", self._popen.stdout), daemon=True),
                threading.Thread(target=self._read_output, args=("stderr", self._popen.stderr), daemon=True),
            ]
            for thread in self._reader_threads:
                thread.start()
            watcher = threading.Thread(target=self._watch, daemon=True)
            watcher.start()

    def mark_skipped(self) -> None:
        with self._lock:
            if self._state != "pending":
                return
            self._state = "skipped"
            self._termination_reason = TerminationReason.SKIPPED
            self._finished_at = time.monotonic()
            self._outcome = ProcessOutcome(
                stdout="",
                stderr="",
                exit_code=None,
                duration=0.0,
                termination_reason=TerminationReason.SKIPPED,
                output_truncated=False,
            )
            self._finished.set()
        self._queue.put(_END)
        self._backend.close()

    def stop(self, grace_period: float = 2.0, reason: TerminationReason = TerminationReason.CANCELLED) -> StopResult:
        if grace_period < 0:
            raise ValueError("grace_period must be non-negative")
        if self._finished.is_set():
            return StopResult(self.id, graceful=True, force_killed=False, tree_clean=True)
        if self._popen is None:
            self.mark_skipped()
            return StopResult(self.id, graceful=True, force_killed=False, tree_clean=True)

        with self._lock:
            self._termination_reason = reason
            self._state = "stopping"

        self._terminate_gracefully()
        graceful = self._wait_for_exit(grace_period)
        force_killed = False
        tree_clean = True
        if not graceful:
            force_killed = True
            tree_clean = self._kill_tree()
            self._wait_for_exit(None)
        return StopResult(self.id, graceful=graceful, force_killed=force_killed, tree_clean=tree_clean)

    def _read_output(self, channel: str, pipe: Any) -> None:
        assert pipe is not None
        try:
            for line in pipe:
                self._save_output(channel, line)
                self._queue.put(StreamEvent(channel, line, datetime.now(timezone.utc)))
        finally:
            pipe.close()

    def _save_output(self, channel: str, text: str) -> None:
        encoded_size = len(text.encode(self._encoding, errors=self._errors))
        with self._lock:
            if self._output_limit is None or self._buffer_sizes[channel] + encoded_size <= self._output_limit:
                self._buffers[channel].append(text)
                self._buffer_sizes[channel] += encoded_size
            else:
                remaining = max(0, self._output_limit - self._buffer_sizes[channel])
                if remaining:
                    self._buffers[channel].append(
                        text.encode(self._encoding, errors=self._errors)[:remaining].decode(
                            self._encoding, errors=self._errors
                        )
                    )
                    self._buffer_sizes[channel] = self._output_limit
                self._output_truncated = True

    def _watch(self) -> None:
        assert self._popen is not None
        if self._timeout is not None:
            timer = threading.Timer(self._timeout, self._timeout_stop)
            timer.daemon = True
            timer.start()
        else:
            timer = None
        self._popen.wait()
        with self._lock:
            self._finished_at = time.monotonic()
        for thread in self._reader_threads:
            thread.join()
        if timer is not None:
            timer.cancel()
        with self._lock:
            if self._termination_reason is None:
                self._termination_reason = (
                    TerminationReason.COMPLETED if self._popen.returncode == 0 else TerminationReason.FAILED
                )
            self._state = "finished" if self._popen.returncode == 0 else "failed"
            self._outcome = ProcessOutcome(
                stdout="".join(self._buffers["stdout"]),
                stderr="".join(self._buffers["stderr"]),
                exit_code=self._popen.returncode,
                duration=(self._finished_at or time.monotonic()) - (self._started_at or time.monotonic()),
                termination_reason=self._termination_reason,
                output_truncated=self._output_truncated,
            )
            self._finished.set()
        self._queue.put(_END)
        self._backend.close()

    def _timeout_stop(self) -> None:
        if not self._finished.is_set():
            self.stop(reason=TerminationReason.TIMEOUT)

    def _wait_for_exit(self, timeout: float | None) -> bool:
        assert self._popen is not None
        try:
            self._popen.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def _terminate_gracefully(self) -> None:
        assert self._popen is not None
        if self._popen.poll() is not None:
            return
        self._backend.terminate(self._popen)

    def _kill_tree(self) -> bool:
        assert self._popen is not None
        if self._popen.poll() is not None:
            return True
        return self._backend.kill_tree(self._popen)
