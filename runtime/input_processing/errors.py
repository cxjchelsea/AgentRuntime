"""Errors raised by the real M1 input processor."""


class InputNormalizationError(ValueError):
    """Raised when a RuntimeInput cannot be safely normalized."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message
