from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .backend import create_backend
from .persistent import ProcessRecord, ProcessStore
from .process import _is_python_command, _parse_command


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        return _start(args)
    if args.command == "status":
        return _status(args)
    if args.command == "output":
        return _output(args)
    if args.command == "stop":
        return _stop(args)
    if args.command == "list":
        return _list(args)
    if args.command == "clean":
        return _clean(args)
    if args.command == "_monitor":
        return _monitor(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procpulse")
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", help="Start a background process")
    start.add_argument("--cwd", default=None)
    start.add_argument("--grace-period", type=float, default=2.0)
    start.add_argument("command_line", nargs=argparse.REMAINDER)

    status = subparsers.add_parser("status", help="Show process status")
    status.add_argument("process_id")

    output = subparsers.add_parser("output", help="Show captured process output")
    output.add_argument("process_id")
    output.add_argument("--stderr", action="store_true")

    stop = subparsers.add_parser("stop", help="Stop a background process")
    stop.add_argument("process_id")
    stop.add_argument("--grace-period", type=float, default=2.0)

    subparsers.add_parser("list", help="List known processes")
    subparsers.add_parser("clean", help="Remove records for finished processes")

    monitor = subparsers.add_parser("_monitor", help=argparse.SUPPRESS)
    monitor.add_argument("record_path")
    return parser


def _start(args: argparse.Namespace) -> int:
    command_line = list(args.command_line)
    if command_line and command_line[0] == "--":
        command_line.pop(0)
    if not command_line:
        print("procpulse start requires a command after --", file=sys.stderr)
        return 2
    if len(command_line) == 1:
        command_line = _parse_command(command_line[0], None)
    if _is_python_command(command_line[0]):
        command_line[0] = sys.executable

    work_dir = os.path.abspath(args.cwd or os.getcwd())
    store = ProcessStore(Path(work_dir) / ".procpulse")
    record = store.create(command_line, work_dir)
    record.grace_period = args.grace_period
    store.save(record)
    record.monitor_pid = _start_monitor(store.path(record.id))
    print(record.id)
    return 0


def _start_monitor(record_path: Path) -> int:
    options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    monitor = subprocess.Popen(
        [sys.executable, "-m", "procpulse.cli", "_monitor", str(record_path)],
        **options,
    )
    return monitor.pid


def _monitor(args: argparse.Namespace) -> int:
    record_path = Path(args.record_path)
    store = ProcessStore(record_path.parent.parent)
    record = _load_record_path(record_path)
    backend = create_backend()
    stdout_handle = open(record.stdout_path, "w", encoding="utf-8")
    stderr_handle = open(record.stderr_path, "w", encoding="utf-8")
    try:
        env = backend.prepare_environment(None)
        options = {
            "args": record.cmd,
            "cwd": record.work_dir,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_handle,
            "stderr": stderr_handle,
            "shell": False,
        }
        options.update(backend.popen_options())
        process = subprocess.Popen(**options)
        backend.attach(process.pid)
        record.pid = process.pid
        record.state = "running"
        record.started_at = time.time()
        store.save(record)

        while process.poll() is None:
            current = store.load(record.id)
            if current.stop_requested:
                backend.terminate(process)
                if _wait_process(process, current.grace_period):
                    record.termination_reason = current.stop_reason
                else:
                    backend.kill_tree(process)
                    process.wait()
                    record.termination_reason = "killed"
                break
            time.sleep(0.2)

        if record.termination_reason is None:
            record.termination_reason = "completed" if process.returncode == 0 else "failed"
        record.exit_code = process.returncode
        record.finished_at = time.time()
        record.state = "finished" if process.returncode == 0 else "failed"
        store.save(record)
        return 0
    finally:
        backend.close()
        stdout_handle.close()
        stderr_handle.close()


def _wait_process(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _load_record_path(path: Path) -> ProcessRecord:
    import json

    with path.open(encoding="utf-8") as handle:
        return ProcessRecord.from_dict(json.load(handle))


def _status(args: argparse.Namespace) -> int:
    try:
        record = ProcessStore().load(args.process_id)
    except OSError:
        print(f"Process not found: {args.process_id}", file=sys.stderr)
        return 1
    _refresh_record_state(record)
    _print_record(record)
    return 0


def _list(args: argparse.Namespace) -> int:
    del args
    for record in ProcessStore().list():
        _refresh_record_state(record)
        _print_record(record)
        print()
    return 0


def _clean(args: argparse.Namespace) -> int:
    del args
    removed = ProcessStore().clean()
    print(f"Removed {removed} finished process record(s).")
    return 0


def _refresh_record_state(record: ProcessRecord) -> None:
    if record.state == "running" and record.pid is not None and not psutil.pid_exists(record.pid):
        record.state = "failed"
        record.finished_at = record.finished_at or time.time()
        record.termination_reason = record.termination_reason or "unknown"
        ProcessStore().save(record)


def _print_record(record: ProcessRecord) -> None:
    uptime = _record_uptime(record)
    print(f"id: {record.id}")
    print(f"state: {record.state}")
    print(f"pid: {record.pid}")
    print(f"uptime: {uptime:.3f}s")
    print(f"cmd: {' '.join(record.cmd)}")
    print(f"work_dir: {record.work_dir}")
    print(f"exit_code: {record.exit_code}")
    print(f"termination_reason: {record.termination_reason}")
    print(f"stdout_path: {record.stdout_path}")
    print(f"stderr_path: {record.stderr_path}")


def _record_uptime(record: ProcessRecord) -> float:
    if record.started_at is None:
        return 0.0
    end = record.finished_at or (
        time.time() if record.state not in {"finished", "failed"} else record.started_at
    )
    return max(0.0, end - record.started_at)


def _output(args: argparse.Namespace) -> int:
    try:
        record = ProcessStore().load(args.process_id)
    except OSError:
        print(f"Process not found: {args.process_id}", file=sys.stderr)
        return 1
    path = record.stderr_path if args.stderr else record.stdout_path
    try:
        with open(path, encoding="utf-8") as handle:
            sys.stdout.write(handle.read())
    except FileNotFoundError:
        pass
    return 0


def _stop(args: argparse.Namespace) -> int:
    store = ProcessStore()
    try:
        record = store.load(args.process_id)
    except OSError:
        print(f"Process not found: {args.process_id}", file=sys.stderr)
        return 1
    if record.state in {"finished", "failed"}:
        print(f"Process already finished: {record.id}")
        return 0
    record.stop_requested = True
    record.grace_period = args.grace_period
    record.stop_reason = "cancelled"
    store.save(record)
    print(f"Stop requested: {record.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
