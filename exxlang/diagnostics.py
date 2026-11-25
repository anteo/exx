"""Diagnostics shared by the EXX compiler stages."""


class ExxError(Exception):
    """An error associated with a line of EXX source."""

    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line
        self.message = message
        self.source = None
