from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Iterable
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

    process_list = list(processes)
    if not process_list:
        return

    output = file or sys.stdout
    messages: queue.Queue[tuple[str, int, StreamEvent | None]] = queue.Queue()

    def consume(index: int, process: ProcessObject) -> None:
        for event in process.stream:
            messages.put(("event", index, event))
        messages.put(("done", index, None))

    readers = [
        threading.Thread(target=consume, args=(index, process), daemon=True)
        for index, process in enumerate(process_list, start=1)
    ]
    for reader in readers:
        reader.start()

    finished_readers = 0
    next_status = 0.0
    while finished_readers < len(process_list):
        now = time.monotonic()
        wait_for = max(0.0, min(status_interval, next_status - now)) if next_status else 0.0
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
        if now >= next_status:
            _print_status(process_list, output)
            next_status = now + status_interval

    for reader in readers:
        reader.join()

    _print_status(process_list, output)


def _print_status(processes: list[ProcessObject], output: TextIO) -> None:
    status_text = " | ".join(
        _format_status(index, process.status)
        for index, process in enumerate(processes, start=1)
    )
    print(f"[status] {status_text}", file=output, flush=True)


def _format_status(index: int, status: ProcessStatus) -> str:
    return (
        f"process_{index}: state={status.state}, "
        f"alive={status.is_alive}, pid={status.pid}, "
        f"uptime={status.uptime:.1f}s"
    )
