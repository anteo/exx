"""Diagnostics shared by the EXX compiler stages."""


class ExxError(Exception):
    """An error associated with a line of EXX source."""

    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line
        self.message = message
        self.source = None


def declaration_conflict(line, message, previous_line, previous_source):
    location = f"{previous_source}:{previous_line}" if previous_source is not None else f"line {previous_line}"
    return ExxError(line, f"{message} (previous declaration at {location})")
