from __future__ import annotations

import sys

import pytest

import procpulse.command as command_module
from procpulse import ProcessManager, UnsafeCommandError, display


def test_single_command_string_returns_one_process() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        "python -c \"print('single', flush=True)\"",
    )

    assert len(processes) == 1
    assert processes[0].wait(timeout=5).stdout.strip() == "single"
    manager.close()


def test_command_string_list_is_normalized_as_individual_commands() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        [
            "python -c \"print('one', flush=True)\"",
            "python -c \"print('two', flush=True)\"",
        ],
        mode="parallel",
    )

    assert len(processes) == 2
    assert [process.wait(timeout=5).stdout.strip() for process in processes] == ["one", "two"]
    manager.close()


def test_invalid_mode_is_rejected_before_starting_processes() -> None:
    manager = ProcessManager()

    with pytest.raises(ValueError, match="mode"):
        manager.run_external_process("python -c pass", mode="sideways")

    assert manager.list() == []
    manager.close()


@pytest.mark.parametrize("unsafe_command", [
    "python -c pass | cat",
    "python -c pass && python -c pass",
    "python -c pass > output.txt",
    "python -c \"print('a|b')\"",
])
def test_unsafe_shell_tokens_are_rejected_before_starting_any_process(unsafe_command: str) -> None:
    manager = ProcessManager()

    with pytest.raises(UnsafeCommandError) as error:
        manager.run_external_process(["python -c pass", unsafe_command], mode="parallel")

    assert "Command 2" in str(error.value)
    assert manager.list() == []
    manager.close()


def test_bare_python_is_resolved_for_each_command() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        ["python -c \"print('resolved', flush=True)\""],
    )

    assert processes[0].wait(timeout=5).exit_code == 0
    assert processes[0].status.cmd[0] == sys.executable
    manager.close()


def test_sequence_starts_commands_in_order() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        [
            "python -c \"print('first', flush=True)\"",
            "python -c \"print('second', flush=True)\"",
        ],
    )

    outcomes = [process.wait(timeout=5) for process in processes]

    assert [outcome.stdout.strip() for outcome in outcomes] == ["first", "second"]
    assert [process.status.state for process in processes] == ["finished", "finished"]
    manager.close()


def test_sequence_failure_skips_later_commands() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        [
            "python -c \"raise SystemExit(3)\"",
            "python -c \"print('must not run', flush=True)\"",
            "python -c \"print('also must not run', flush=True)\"",
        ],
    )

    first_outcome = processes[0].wait(timeout=5)
    skipped_outcomes = [process.wait(timeout=5) for process in processes[1:]]

    assert first_outcome.exit_code == 3
    assert processes[0].status.state == "failed"
    assert [process.status.state for process in processes[1:]] == ["skipped", "skipped"]
    assert all(outcome.termination_reason.value == "skipped" for outcome in skipped_outcomes)
    assert all(process.status.pid is None for process in processes[1:])
    manager.close()


def test_parallel_failure_does_not_stop_siblings() -> None:
    manager = ProcessManager()

    processes = manager.run_external_process(
        [
            "python -c \"raise SystemExit(4)\"",
            "python -c \"print('sibling', flush=True)\"",
        ],
        mode="parallel",
    )

    outcomes = [process.wait(timeout=5) for process in processes]

    assert outcomes[0].exit_code == 4
    assert outcomes[1].exit_code == 0
    assert outcomes[1].stdout.strip() == "sibling"
    manager.close()


def test_sequence_batch_can_use_existing_display() -> None:
    manager = ProcessManager()
    processes = manager.run_external_process(
        [
            "python -c \"print('display-one', flush=True)\"",
            "python -c \"print('display-two', flush=True)\"",
        ],
    )
    from io import StringIO

    output = StringIO()
    display(processes, status_interval=0.01, file=output)

    rendered = output.getvalue()
    assert "[process_1][stdout] display-one" in rendered
    assert "[process_2][stdout] display-two" in rendered
    assert all(process.status.state == "finished" for process in processes)
    manager.close()


def test_windows_shell_tokens_are_rejected_by_windows_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ProcessManager()
    monkeypatch.setattr(command_module.os, "name", "nt")

    with pytest.raises(UnsafeCommandError, match="\\^"):
        manager.run_external_process("python -c pass ^ echo blocked")

    assert manager.list() == []
    manager.close()
