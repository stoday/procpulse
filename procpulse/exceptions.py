class ProcessPulseError(Exception):
    """Base exception for ProcPulse."""


class ManagerClosedError(ProcessPulseError):
    """Raised when an operation is attempted on a closed manager."""


class ProcessNotFoundError(ProcessPulseError):
    """Raised when a manager does not know the requested process ID."""


class ProcessStartError(ProcessPulseError):
    """Raised when an external process cannot be started."""


class UnsafeCommandError(ProcessPulseError):
    """Raised when a command contains unsupported shell control syntax."""


class ProcessTreeTerminationError(ProcessPulseError):
    """Raised when a controlled process tree cannot be fully stopped."""
