from typing import Any


class ReplayError(Exception):
    """Base exception for replay errors."""

    pass


class ReplayDivergenceError(ReplayError):
    """Raised when execution diverges from recorded session trace."""

    def __init__(
        self,
        seq: int,
        expected_type: str,
        expected_name: str,
        expected_args: Any,
        actual_type: str,
        actual_name: str,
        actual_args: Any,
        message: str | None = None,
    ):
        self.seq = seq
        self.expected_type = expected_type
        self.expected_name = expected_name
        self.expected_args = expected_args
        self.actual_type = actual_type
        self.actual_name = actual_name
        self.actual_args = actual_args

        msg = (
            message
            or f"Replay divergence at step #{seq}: "
            f"Expected {expected_type} '{expected_name}' with args {expected_args}, "
            f"but got {actual_type} '{actual_name}' with args {actual_args}."
        )
        super().__init__(msg)


class ReplayCompletedError(ReplayError):
    """Raised when the agent attempts a call after all recorded events are exhausted."""

    def __init__(self, requested_type: str, requested_name: str):
        super().__init__(
            f"Replay trace exhausted for unexpected {requested_type} '{requested_name}'."
        )
