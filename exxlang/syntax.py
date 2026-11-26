"""Abstract syntax tree for EXX source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Expr:
    kind: str
    value: str | int | None
    args: tuple[Expr, ...]
    line: int


@dataclass(frozen=True)
class AsmBlock:
    text: str
    line: int
    start: int
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    clobbers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stmt:
    kind: str
    line: int
    value: Expr | AsmBlock | str | tuple[tuple[str, str], ...] | None = None
    target: Expr | None = None
    body: tuple[Stmt, ...] = ()
    otherwise: tuple[Stmt, ...] = ()
    op: str | None = None
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class Param:
    name: str
    register: str | None
    type_name: str | None
    line: int
    stack_offset: int | None = None


@dataclass(frozen=True)
class Proc:
    name: str
    params: tuple[Param, ...]
    outputs: tuple[str, ...]
    clobbers: tuple[str, ...]
    body: tuple[Stmt, ...] | None
    line: int
    end_line: int
    start: int = 0
    end: int = 0
    frame: str | None = None


@dataclass(frozen=True)
class Field:
    name: str
    type_name: str
    line: int


@dataclass(frozen=True)
class Layout:
    name: str
    size: int
    line: int


@dataclass(frozen=True)
class DataSymbol:
    name: str
    line: int
    type_name: str | None
    initializer: Expr | None
    start: int


@dataclass(frozen=True)
class Program:
    procs: tuple[Proc, ...]
    data: tuple[DataSymbol, ...] = ()
    fields: tuple[Field, ...] = ()
    assembly: tuple[AsmBlock, ...] = ()
    layouts: tuple[Layout, ...] = ()
