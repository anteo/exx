"""Physical operands and selected instructions consumed by the ABI analysis."""

from dataclasses import dataclass, field


class TargetError(ValueError):
    """A platform cannot lower the requested operation."""


@dataclass(frozen=True)
class Operand:
    kind: str
    text: str
    width: int = 0
    read_only: bool = False


@dataclass(frozen=True)
class StaticData:
    name: str
    width: int
    initializer: str
    externals: frozenset[str]
    start: int


@dataclass(frozen=True)
class Directive:
    name: str | None
    value: str
    start: int


@dataclass(frozen=True)
class StructMember:
    name: str
    type_name: str
    size: int
    offset: int


@dataclass(frozen=True)
class StructDefinition:
    name: str
    size: int
    members: tuple[StructMember, ...]


@dataclass(frozen=True)
class Transfer:
    """Ordered storage cells for a stack operation or simultaneous exchange."""

    kind: str
    first: tuple
    second: tuple = ()


@dataclass(frozen=True)
class Instruction:
    mnemonic: str
    operands: tuple[str, ...] = ()
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    branch_target: str | None = None
    falls_through: bool = True
    transfer: Transfer | None = None
    invalidates: frozenset[str] = frozenset()
    source_offset: int = field(default=0, compare=False)
    encoded_size: int | None = field(default=None, compare=False)
