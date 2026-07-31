# ProcPulse API Reference

## Starting commands

`run_external_process()` accepts one complete command string or a sequence of complete command strings. It returns one `ProcessObject` per command in input order:

```python
processes = manager.run_external_process(
    ["python prepare.py", "python build.py"],
    mode="sequence",
)
```

Use `mode="sequence"` to start each command only after the preceding command succeeds. Sequence is the default. A failure prevents later commands from starting; those entries finish with `state="skipped"`, no OS PID, and `termination_reason="skipped"`.

Use `mode="parallel"` for independent commands:

```python
processes = manager.run_external_process(
    ["python lint.py", "python test.py"],
    mode="parallel",
)
```

A parallel failure does not stop sibling processes. Every returned process keeps its own ID, PID, status, stream, and outcome.

## Start options

- `command`: one command string or a sequence of command strings. Every string is parsed into argv after the complete batch passes safety preflight.
- `mode`: `"sequence"` or `"parallel"`; defaults to `"sequence"`.
- `cwd`: shared working directory. `None` uses the current directory; `status.work_dir` records the resolved absolute path.
- `env`: shared child environment. `None` inherits the current environment; a mapping is the complete child environment and is not automatically merged with `os.environ`.
- `encoding`: stdout/stderr text encoding; defaults to `"utf-8"`.
- `errors`: stdout/stderr decoding error policy; defaults to `"replace"`.
- `output_limit`: maximum saved bytes per process and channel; defaults to 10 MiB. Pipes continue draining after truncation. `None` removes the limit.
- `timeout`: maximum seconds for each process, measured from its actual start. `None` disables the timeout.

`shell` is not an option. ProcPulse uses argv, `shell=False`, `stdin=DEVNULL`, and stdout/stderr pipes. Unsupported shell-control tokens such as pipes, chaining, separators, and redirection fail atomic preflight with `UnsafeCommandError`; no process in that batch starts. Express the workflow as separate ProcPulse commands with sequence or parallel scheduling.

Bare `python`, `python3`, and Windows Python launcher names resolve to the current `sys.executable`. Explicit interpreter paths remain unchanged.

## Stream and outcome

Consume an unfinished process once:

```python
process = processes[0]
for event in process.stream:
    print(event.channel, event.text, event.timestamp)
```

Each event has `channel` (`stdout` or `stderr`), `text`, and a UTC timestamp. The stream ends only after both pipes are drained.

When finished, use the outcome rather than trying to consume the stream again:

```python
outcome = process.outcome
print(outcome.to_string())
```

Termination reasons are `completed`, `failed`, `cancelled`, `timeout`, `killed`, and `skipped`.

## Multiple-process display

Pass the returned process list directly to the manager:

```python
manager.display(processes)
```

`display()` reads unfinished streams concurrently, groups completed status before active status, and displays already-finished processes once without replaying their streams. Already-finished output remains available through `outcome.stdout` and `outcome.stderr`.

## Persistent CLI control

Use the CLI when control must continue after the command that starts the process returns:

```bash
procpulse start -- python long_running.py
procpulse list
procpulse status <process_id>
procpulse output <process_id>
procpulse display <process_id_1> <process_id_2>
procpulse stop <process_id>
procpulse clean
```

Each persisted record includes process ID, state, PID, uptime, effective command, working directory, exit code, termination reason, and stdout/stderr paths. Records and output default to `.procpulse/` in the target working directory; `PROCPULSE_HOME` selects another location. A background monitor owns the child process and performs platform-specific termination. `clean` removes finished or failed records and preserves active records.

## Lifecycle rules

Call `manager.stop(process.id, grace_period=2.0)` for graceful termination followed by force kill when needed. Call `manager.close()` when the manager is no longer needed. A closed manager rejects new work; `close(wait=True)` waits for tracked processes and output draining without automatically stopping active processes.
