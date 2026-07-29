# ProcPulse API Reference

## Starting a process

Use any executable plus arguments, not only Python:

```python
process = manager.run_external_process(
    "python",
    args=["script.py", "--verbose"],
)

git_process = manager.run_external_process("git", args=["status"])
ls_process = manager.run_external_process("ls", args=["-la"])
```

or a command string that is parsed into argv:

```python
process = manager.run_external_process("python script.py --verbose")
git_process = manager.run_external_process("git status")
```

Use `shell=False` semantics. Bare `python`, `python3`, and Windows Python launcher names resolve to the current `sys.executable`; explicit interpreter paths remain unchanged. This Python-specific resolution is only a convenience and does not restrict commands to Python.

Supported options include `cwd`, `env`, `encoding`, `errors`, `output_limit`, and `timeout`. `status.work_dir` records the resolved absolute working directory, and `status.cmd` records the effective immutable command tuple.

## Stream and outcome

Consume an unfinished process once:

```python
for event in process.stream:
    print(event.channel, event.text, event.timestamp)
```

Each event has `channel` (`stdout` or `stderr`), `text`, and a UTC timestamp. The stream ends only after both pipes are drained.

When finished, use the outcome rather than trying to consume the stream again:

```python
outcome = process.outcome
print(outcome.to_string())
```

`termination_reason` values are `completed`, `failed`, `cancelled`, `timeout`, or `killed`.

## Multiple processes

Use the manager helper when several processes should be observed together:

```python
manager.display([process_1, process_2])
```

`display()` reads unfinished streams concurrently, groups completed status before active status, and displays already-finished processes once without replaying their streams. Already-finished output remains available through `outcome.stdout` and `outcome.stderr`.

## Persistent CLI control

Use the CLI when control must continue after the command that starts the process returns:

```bash
procpulse start -- python long_running.py
procpulse list
procpulse status <process_id>
procpulse output <process_id>
procpulse stop <process_id>
```

Use `list` to discover persisted processes. Each record includes process ID, state, PID, uptime, effective command, working directory, exit code, termination reason, and stdout/stderr file paths. The CLI stores records and stdout/stderr files under `~/.procpulse/` by default. Set `PROCPULSE_HOME` for an isolated workspace or test run. A background monitor owns the child process and performs the platform-specific termination flow.

## Lifecycle rules

Call `manager.stop(process.id, grace_period=2.0)` to request graceful termination followed by force kill if needed. Call `manager.close()` after the manager is no longer needed. A closed manager rejects new processes.
