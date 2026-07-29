from __future__ import annotations

import sys
import time
from io import StringIO

import pytest

from procpulse import (
    ManagerClosedError,
    ProcessManager,
    ProcessNotFoundError,
    ProcessStartError,
    TerminationReason,
    display,
)


def test_stream_merges_channels_and_preserves_tail_output() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        sys.executable,
        args=[
            "-c",
            "import sys; print('out-1', flush=True); print('err-1', file=sys.stderr, flush=True); print('out-2', end='')",
        ],
    )

    events = list(process.stream)
    outcome = process.wait()

    assert {event.channel for event in events} == {"stdout", "stderr"}
    assert "out-1" in outcome.stdout
    assert "out-2" in outcome.stdout
    assert "err-1" in outcome.stderr
    assert outcome.termination_reason is TerminationReason.COMPLETED
    assert all(event.timestamp.tzinfo is not None for event in events)
    manager.close()


def test_bare_python_command_uses_current_interpreter() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        "python",
        args=["-c", "print('resolved', flush=True)"],
    )

    events = list(process.stream)

    assert process.wait().exit_code == 0
    assert [event.text.strip() for event in events] == ["resolved"]
    manager.close()


def test_command_string_can_include_arguments() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        "python -c \"print('inline command', flush=True)\"",
    )

    events = list(process.stream)

    assert process.wait().exit_code == 0
    assert [event.text.strip() for event in events] == ["inline command"]
    manager.close()


def test_output_limit_does_not_stop_pipe_draining() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        sys.executable,
        args=["-c", "print('x' * 10000)"],
        output_limit=32,
    )

    list(process.stream)
    outcome = process.wait()

    assert outcome.output_truncated is True
    assert len(outcome.stdout.encode("utf-8")) <= 32
    assert outcome.exit_code == 0
    manager.close()


def test_stop_uses_graceful_termination_before_force_kill() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        sys.executable,
        args=["-c", "import time; time.sleep(30)"],
    )

    result = manager.stop(process.id, grace_period=1.0)
    outcome = process.wait()

    assert result.graceful is True
    assert result.force_killed is False
    assert outcome.termination_reason is TerminationReason.CANCELLED
    manager.close()


def test_timeout_records_timeout_reason() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(
        sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        timeout=0.05,
    )

    outcome = process.wait(timeout=5)

    assert outcome.termination_reason is TerminationReason.TIMEOUT
    manager.close()


def test_start_failure_is_wrapped() -> None:
    manager = ProcessManager()

    with pytest.raises(ProcessStartError):
        manager.run_external_process("definitely-not-a-real-executable")

    manager.close()


def test_manager_rejects_unknown_id_and_new_work_after_close() -> None:
    manager = ProcessManager()

    with pytest.raises(ProcessNotFoundError):
        manager.stop("missing")

    manager.close()
    with pytest.raises(ManagerClosedError):
        manager.run_external_process(sys.executable, args=["-c", "pass"])


def test_list_filters_by_state() -> None:
    manager = ProcessManager()
    process = manager.run_external_process(sys.executable, args=["-c", "pass"])
    process.wait(timeout=5)

    assert process in manager.list(filter="finished")
    assert process not in manager.list(filter="running")
    manager.close()


def test_display_consumes_multiple_process_streams_and_statuses() -> None:
    manager = ProcessManager()
    processes = [
        manager.run_external_process(sys.executable, args=["-c", "print('one', flush=True)"]),
        manager.run_external_process(sys.executable, args=["-c", "print('two', flush=True)"]),
    ]
    output = StringIO()

    display(processes, status_interval=0.01, file=output)

    rendered = output.getvalue()
    assert "[process_1][stdout] one" in rendered
    assert "[process_2][stdout] two" in rendered
    assert "[status]" in rendered
    manager.close()
