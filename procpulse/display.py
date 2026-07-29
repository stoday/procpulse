from __future__ import annotations

import queue
import shlex
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from typing import TextIO

from .models import ProcessStatus, StreamEvent
from .process import ProcessObject


def display(
    processes: Iterable[ProcessObject],
    *,
    status_interval: float = 0.5,
    file: TextIO | None = None,
) -> None:
    """Display events and status for multiple processes until they finish.

    Each process stream is consumed by a background reader. Output is written
    by this function's single coordinator loop, preventing concurrent reader
    threads from interleaving partial lines.
    """
    if status_interval <= 0:
        raise ValueError("status_interval must be greater than zero")

    entries = list(enumerate(processes, start=1))
    if not entries:
        return

    output = file or sys.stdout
    completed = [
        (index, process)
        for index, process in entries
        if process.outcome is not None
    ]
    active = [
        (index, process)
        for index, process in entries
        if process.outcome is None
    ]

    if completed:
        _print_status(completed, output)
    if not active:
        return

    messages: queue.Queue[tuple[str, int, StreamEvent | None]] = queue.Queue()

    def consume(index: int, process: ProcessObject) -> None:
        for event in process.stream:
            messages.put(("event", index, event))
        messages.put(("done", index, None))

    readers = [
        threading.Thread(target=consume, args=(index, process), daemon=True)
        for index, process in active
    ]
    for reader in readers:
        reader.start()

    finished_readers = 0
    next_status = 0.0
    status_polling = any(process.status.is_alive for _, process in active)
    status_printed = False
    while finished_readers < len(active):
        now = time.monotonic()
        if status_polling and not any(process.status.is_alive for _, process in active):
            _print_status(active, output)
            status_printed = True
            status_polling = False

        wait_for = (
            max(0.0, min(status_interval, next_status - now))
            if status_polling and next_status
            else (0.0 if status_polling else None)
        )
        try:
            kind, index, event = messages.get(timeout=wait_for)
        except queue.Empty:
            kind, index, event = "status", -1, None

        if kind == "event":
            assert event is not None
            print(
                f"[process_{index}][{event.channel}] {event.text.rstrip()}",
                file=output,
                flush=True,
            )
        elif kind == "done":
            finished_readers += 1

        now = time.monotonic()
        if status_polling and now >= next_status:
            _print_status(active, output)
            next_status = now + status_interval

    for reader in readers:
        reader.join()

    if not status_printed:
        _print_status(active, output)


def _print_status(entries: Sequence[tuple[int, ProcessObject]], output: TextIO) -> None:
    completed: list[str] = []
    active: list[str] = []
    for index, process in entries:
        status = process.status
        line = _format_status(index, status)
        if status.state in {"finished", "failed"}:
            completed.append(line)
        else:
            active.append(line)

    print("[status]", file=output, flush=True)
    if completed:
        print("  completed:", file=output, flush=True)
        for line in completed:
            print(f"    {line}", file=output, flush=True)
    if active:
        print("  active:", file=output, flush=True)
        for line in active:
            print(f"    {line}", file=output, flush=True)


def _format_status(index: int, status: ProcessStatus) -> str:
    return (
        f"process_{index}: state={status.state}, "
        f"alive={status.is_alive}, pid={status.pid}, "
        f"uptime={status.uptime:.1f}s, "
        f"cmd={shlex.join(status.cmd)}"
    )
