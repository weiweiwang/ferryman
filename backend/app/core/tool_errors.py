from __future__ import annotations


class RetryableToolError(RuntimeError):
    """Tool failure that should be retried by the model before surfacing."""

    def __init__(self, message: str, *, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type
