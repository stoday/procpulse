---
name: process-execution-control
description: Implement, debug, review, and document safe cross-platform execution of arbitrary external commands and programs through ProcPulse, including stdout/stderr streaming, lifecycle management, timeouts, cancellation, process-tree cleanup, nested ProcPulse processes, display helpers, persistent CLI control, and platform backends. Use when working on ProcPulse or any task that requires observable and controllable subprocess execution.
---

# Process Execution Control

Use this skill when changing or diagnosing ProcPulse, or when implementing a workflow that must safely execute, observe, stop, and report arbitrary external commands such as Python programs, git, ls, npm, shell scripts, or compiled binaries.

## Core workflow

1. Inspect `PRD.md`, `README.md`, `dev_docs/`, the package modules, and tests before changing behavior.
2. Preserve the public lifecycle model: `ProcessManager` creates and tracks `ProcessObject`; `ProcessObject` owns status, stream, and outcome.
3. Keep command execution argument-based with `shell=False`. Parse a command string into argv only when required, and resolve bare `python` launchers to `sys.executable`.
4. Drain stdout and stderr concurrently. Emit typed `StreamEvent` objects with `channel`, `text`, and UTC `timestamp`; never allow a pipe buffer to deadlock the child.
5. Treat `stream` as a synchronous, single-consumer iterator. If a process is already finished, use `outcome.stdout` and `outcome.stderr` instead of trying to replay its stream.
6. For stop and timeout, use graceful termination first, wait for the grace period, then force-kill the controlled process scope and wait for output draining and resource cleanup.
7. Keep platform-specific process control behind the backend interface. Do not put Windows API details in the shared process lifecycle code.
8. Update tests and the relevant user/developer documentation with every lifecycle or public API change.
9. Run syntax checks and the full test suite. Report platform-specific tests that cannot run on the current operating system.

## Agent-operated long-running commands

Prefer the persistent CLI when the agent needs to start a command, regain control, inspect it later, and decide whether to stop it:

```text
procpulse start -- COMMAND ARGS...
procpulse list
procpulse status <process_id>
procpulse output <process_id>
procpulse display <process_id_1> <process_id_2>
procpulse stop <process_id>
procpulse clean
```

Use `list` to discover all persisted records and their state, PID, uptime, effective command, working directory, exit code, termination reason, and captured output paths. Use `display` when several persistent processes should be observed together; it reads their saved stdout/stderr, groups completed before active status, and returns after all finish. Use `clean` after a task to remove records and output for finished or failed processes; never use it as a substitute for stopping an active process. Do not use a blocking foreground command for work whose completion time is unknown unless a timeout or explicit cancellation policy is acceptable. Treat `process_id` as the handle to carry between agent steps. Read list/status and output before deciding whether a slow process is healthy, stalled, or should be stopped.

## Public API invariants

- `ProcessManager.list()` returns tracked processes and can filter by status state.
- `ProcessManager.display()` consumes only unfinished processes and prints completed processes once; it blocks until active processes finish.
- `ProcessStatus` exposes `state`, `is_alive`, `pid`, `uptime`, `return_code`, `cmd`, and `work_dir`.
- `ProcessOutcome` exposes separated stdout/stderr, exit code, duration, termination reason, truncation state, and `to_string()` for readable multiline output.
- A process ID is a ProcPulse identifier, not the operating-system PID.
- `outcome` is the final result; do not infer completion solely from `status.is_alive` while output draining is still in progress.

## Change guidance

Read the relevant reference before editing a fragile area:

- Public behavior and examples: [references/api.md](references/api.md)
- Process groups, nested processes, and platform cleanup: [references/platform-backends.md](references/platform-backends.md)

When a requested behavior conflicts with the PRD, identify the conflict and update the specification before implementing a breaking change. Avoid claiming that every descendant can always be killed: document permission failures, detached sessions, daemonization, service managers, and PID reuse as limits.

## Validation checklist

- Test normal completion with stdout, stderr, no output, and non-zero exit code.
- Test output tail draining and output-limit truncation.
- Test graceful stop, timeout, force kill, repeated stop, and unknown process IDs.
- Test `manager.display()` with active processes, already-finished processes, and mixed active/completed lists.
- Test root and nested process trees on Linux/macOS; test Job Object and fallback behavior on Windows.
- Verify `status.cmd`, `status.work_dir`, and formatted outcomes in diagnostics.
