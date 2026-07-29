# Platform Backend Reference

## Backend boundary

Keep shared lifecycle, output readers, status, and outcome construction in `procpulse/process.py`. Platform-specific process scope operations belong behind `ProcessBackend` in `procpulse/backend.py`.

## Linux/macOS

`UnixProcessBackend` creates a root process group with `start_new_session=True`. It propagates `PROCPULSE_PROCESS_GROUP=1` to child environments. A nested ProcPulse detects that marker and inherits the current process group instead of creating another session.

Root processes may use `os.killpg()` because they own the group. Nested processes must not use `killpg()` because that could kill the outer process or siblings; use `psutil.Process(pid).children(recursive=True)` and signal the nested process plus its descendants.

Use graceful `SIGTERM` first and `SIGKILL` after the grace period. Catch `NoSuchProcess`, `ProcessLookupError`, and races caused by short-lived children. Never promise cleanup for processes that call `setsid()`, daemonize, enter a service manager, or exceed the caller's permissions.

## Windows

`WindowsProcessBackend` should create a Job Object, set `KILL_ON_JOB_CLOSE`, and assign the spawned process to it. Use `TerminateJobObject` for force cleanup. If Job Object creation or assignment fails, use `taskkill /PID <pid> /T /F` as the fallback and report the cleanup result.

Keep Windows `ctypes` declarations isolated in `procpulse/windows_process.py`; do not import that module on non-Windows systems through the normal backend selection path.

## Testing

Use platform-specific tests for root groups, nested ProcPulse processes, multi-level descendants, graceful termination, force kill, detached processes, and permission failures. Skip Windows-only tests on Unix and Unix process-group tests on Windows, but keep syntax and API checks cross-platform.
