from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Sequence

from .exceptions import UnsafeCommandError


_UNIX_FORBIDDEN_TOKENS = (
    "&&",
    "||",
    ">>",
    "<<",
    "$(",
    "|",
    ";",
    ">",
    "<",
    "&",
    "`",
    "\n",
    "\r",
)
_WINDOWS_FORBIDDEN_TOKENS = (
    "&&",
    "||",
    ">>",
    "<<",
    "|",
    ";",
    ">",
    "<",
    "&",
    "^",
    "`",
    "$(",
    "\n",
    "\r",
)


def normalize_commands(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return [command]
    if not isinstance(command, Sequence):
        raise TypeError("command must be a string or a sequence of command strings")
    commands = list(command)
    if not commands or any(not isinstance(item, str) for item in commands):
        raise TypeError("command sequence must contain at least one string command")
    return commands


def parse_commands(command: str | Sequence[str]) -> list[list[str]]:
    command_strings = normalize_commands(command)
    parsed: list[list[str]] = []
    for index, command_text in enumerate(command_strings, start=1):
        _validate_shell_tokens(command_text, index)
        argv = shlex.split(command_text, posix=os.name != "nt")
        if not argv:
            raise ValueError(f"command {index} must not be empty")
        if _is_python_command(argv[0]):
            argv[0] = sys.executable
        parsed.append(argv)
    return parsed


def _validate_shell_tokens(command: str, index: int) -> None:
    tokens = _WINDOWS_FORBIDDEN_TOKENS if os.name == "nt" else _UNIX_FORBIDDEN_TOKENS
    for token in tokens:
        if token in command:
            raise UnsafeCommandError(
                f"Command {index} contains forbidden shell syntax {token!r}. "
                "Run each command separately through ProcPulse instead of chaining commands."
            )


def _is_python_command(command: str) -> bool:
    if os.path.dirname(command):
        return False
    return command.lower() in {"python", "python3", "python.exe", "python3.exe"}
