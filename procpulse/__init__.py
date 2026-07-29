"""Public API for ProcPulse."""

from .exceptions import (
    ManagerClosedError,
    ProcessNotFoundError,
    ProcessPulseError,
    ProcessStartError,
    ProcessTreeTerminationError,
)
from .display import display
from .manager import ProcessManager, build
from .models import (
    ProcessOutcome,
    ProcessStatus,
    StopResult,
    StreamEvent,
    TerminationReason,
)
from .process import ProcessObject

__all__ = [
    "ManagerClosedError",
    "display",
    "ProcessManager",
    "ProcessNotFoundError",
    "ProcessOutcome",
    "ProcessObject",
    "ProcessPulseError",
    "ProcessStartError",
    "ProcessStatus",
    "ProcessTreeTerminationError",
    "StopResult",
    "StreamEvent",
    "TerminationReason",
    "build",
]
