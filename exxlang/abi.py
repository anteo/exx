"""Load ABI declaration files for one translation unit."""

from pathlib import Path

from .diagnostics import ExxError
from .parser import parse


class AbiImports:
    def __init__(self, source_path):
        self.units = {}
        self.active = {} if source_path is None else {Path(source_path).resolve(): source_path}

    def load(self, path, text=None):
        key = Path(path).resolve()
        if key in self.active:
            chain = (*self.active.values(), path)
            raise ValueError("cyclic ABI import: " + " → ".join(map(str, chain)))
        if key in self.units:
            return
        if text is None:
            text = key.read_text(encoding="utf-8")
        try:
            program = parse(text)
        except ExxError as error:
            error.source = path
            raise
        self.active[key] = path
        try:
            self.load_uses(program, path)
            self.units[key] = (path, program)
        finally:
            del self.active[key]

    def load_uses(self, program, source_path):
        for use in program.uses:
            if source_path is None:
                raise ExxError(use.line, "use requires a source file path")
            try:
                self.load(Path(source_path).parent / use.path)
            except (OSError, ValueError, RuntimeError) as error:
                failure = ExxError(use.line, f"cannot load ABI {use.path!r}: {error}")
                failure.source = source_path
                raise failure from error
