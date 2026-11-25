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
class Stmt:
    kind: str
    line: int
    value: Expr | tuple[tuple[str, str], ...] | None = None
    target: Expr | None = None
    body: tuple[Stmt, ...] = ()
    otherwise: tuple[Stmt, ...] = ()
    op: str | None = None


@dataclass(frozen=True)
class Param:
    name: str
    register: str
    type_name: str | None
    line: int


@dataclass(frozen=True)
class Proc:
    name: str
    params: tuple[Param, ...]
    outputs: tuple[str, ...]
    clobbers: tuple[str, ...]
    body: tuple[Stmt, ...] | None
    line: int


@dataclass(frozen=True)
class Program:
    procs: tuple[Proc, ...]
