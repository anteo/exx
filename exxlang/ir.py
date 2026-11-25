"""Physical operands and selected instructions consumed by the ABI analysis."""

from dataclasses import dataclass


class TargetError(ValueError):
    """A platform cannot lower the requested operation."""


@dataclass(frozen=True)
class Operand:
    kind: str
    text: str
    width: int = 0


@dataclass(frozen=True)
class Instruction:
    mnemonic: str
    operands: tuple[str, ...] = ()
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    branch_target: str | None = None
    falls_through: bool = True
