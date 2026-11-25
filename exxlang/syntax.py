"""Source syntax and abstract syntax tree for EXX."""

from __future__ import annotations

import re
from dataclasses import dataclass


class ExxError(Exception):
    """An error associated with a line of EXX source."""

    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line
        self.message = message


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


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    line: int


_TOKEN = re.compile(
    r"(?P<space>[ \t\v\f]+)"
    r"|(?P<newline>\r\n?|\n)"
    r"|(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)"
    r"|(?P<name>[a-zA-Z_][a-zA-Z_0-9]*)"
    r"|(?P<int>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)"
    r"|(?P<punct>->|→|\|\||&&|==|!=|<=|>=|\^=|\+=|-=|[(){}:;,!+\-.^<>=])"
)
_ASSIGN = frozenset({"=", "^=", "+=", "-="})
_KEYWORDS = frozenset({"extern", "clobbers", "if", "else", "while", "return"})
_PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "^": 3,
    "==": 4,
    "!=": 4,
    "<": 5,
    "<=": 5,
    ">": 5,
    ">=": 5,
    "+": 6,
    "-": 6,
}


def _tokenize(source: str) -> list[_Token]:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    tokens = []
    line = 1
    parentheses = 0
    offset = 0
    while offset < len(source):
        match = _TOKEN.match(source, offset)
        if match is None:
            if source.startswith("/*", offset):
                raise ExxError(line, "unterminated block comment")
            raise ExxError(line, f"unexpected character {source[offset]!r}")
        offset = match.end()
        kind = match.lastgroup
        value = match.group()
        if kind in {"comment", "newline"}:
            if "\n" in value and parentheses == 0:
                tokens.append(_Token("newline", "\n", line))
            line += value.count("\n")
        elif kind != "space":
            if value == "(":
                parentheses += 1
            elif value == ")" and parentheses > 0:
                parentheses -= 1
            if kind == "name" and value in _KEYWORDS:
                kind = "keyword"
            tokens.append(_Token(kind, value, line))
    tokens.append(_Token("eof", "", line))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.index = 0

    @property
    def token(self) -> _Token:
        return self.tokens[self.index]

    def _advance(self) -> _Token:
        token = self.token
        self.index += 1
        return token

    def _accept(self, value: str) -> bool:
        if self.token.value != value:
            return False
        self._advance()
        return True

    def _accept_after_newlines(self, *values: str) -> bool:
        index = self.index
        self._skip_newlines()
        if self.token.value in values:
            self._advance()
            return True
        self.index = index
        return False

    def _expect(self, value: str) -> _Token:
        if self.token.value == value:
            return self._advance()
        raise ExxError(self.token.line, f"expected {value!r}, found {self._found()}")

    def _expect_name(self) -> _Token:
        if self.token.kind == "name":
            return self._advance()
        raise ExxError(self.token.line, f"expected a name, found {self._found()}")

    def _found(self) -> str:
        if self.token.kind == "eof":
            return "end of input"
        if self.token.kind == "newline":
            return "end of line"
        return repr(self.token.value)

    def _skip_newlines(self) -> None:
        while self.token.kind == "newline":
            self._advance()

    def _skip_separators(self) -> None:
        while self.token.kind == "newline" or self.token.value == ";":
            self._advance()

    def _expect_statement_end(self) -> None:
        if self.token.kind in {"newline", "eof"}:
            return
        if self._accept(";") or self.token.value == "}":
            return
        raise ExxError(self.token.line, f"expected end of statement, found {self._found()}")

    def program(self) -> Program:
        procs = []
        self._skip_separators()
        while self.token.kind != "eof":
            procs.append(self._procedure())
            self._skip_separators()
        return Program(tuple(procs))

    def _procedure(self) -> Proc:
        line = self.token.line
        is_extern = self._accept("extern")
        name = self._expect_name().value
        self._expect("(")
        params = []
        if not self._accept(")"):
            while True:
                params.append(self._parameter())
                if self._accept(")"):
                    break
                self._expect(",")
        outputs = ()
        if self._accept_after_newlines("→", "->"):
            outputs = self._names() if self.token.value == "(" else (self._expect_name().value,)
        clobbers = self._names() if self._accept_after_newlines("clobbers") else ()
        if is_extern:
            self._expect_statement_end()
            body = None
        else:
            self._skip_newlines()
            body = self._block()
        return Proc(name, tuple(params), outputs, clobbers, body, line)

    def _parameter(self) -> Param:
        name = self._expect_name()
        type_name = self._qualified_name() if self._accept(":") else None
        if not self._accept("->"):
            self._expect("→")
        register = self._expect_name().value
        return Param(name.value, register, type_name, name.line)

    def _qualified_name(self) -> str:
        parts = [self._expect_name().value]
        while self._accept("."):
            parts.append(self._expect_name().value)
        return ".".join(parts)

    def _names(self) -> tuple[str, ...]:
        self._expect("(")
        names = []
        if not self._accept(")"):
            while True:
                names.append(self._expect_name().value)
                if self._accept(")"):
                    break
                self._expect(",")
        return tuple(names)

    def _block(self) -> tuple[Stmt, ...]:
        self._expect("{")
        statements = []
        self._skip_separators()
        while self.token.value != "}":
            if self.token.kind == "eof":
                raise ExxError(self.token.line, "expected '}' before end of input")
            statements.append(self._statement())
            self._skip_separators()
        self._advance()
        return tuple(statements)

    def _body(self) -> tuple[Stmt, ...]:
        self._skip_newlines()
        if self.token.value == "{":
            return self._block()
        return (self._statement(),)

    def _statement(self) -> Stmt:
        token = self.token
        if token.value in {"if", "while"}:
            return self._control()
        if self._accept("return"):
            result = None
            if self.token.kind not in {"newline", "eof"} and self.token.value not in {"}", ";"}:
                result = self._expression()
            self._expect_statement_end()
            return Stmt("return", token.line, result)
        target = self._expression()
        if self._accept("→"):
            aliases = self._binding_names(target)
            registers = self._names() if self.token.value == "(" else (self._expect_name().value,)
            if not aliases or len(aliases) != len(registers):
                raise ExxError(token.line, "a binding needs one register per name")
            self._expect_statement_end()
            return Stmt("bind", token.line, tuple(zip(aliases, registers)))
        if self.token.value in _ASSIGN:
            operator = self._advance().value
            value = self._expression()
            self._expect_statement_end()
            return Stmt("assign", token.line, value, target=target, op=operator)
        if target.kind == "call":
            self._expect_statement_end()
            return Stmt("call", token.line, target)
        raise ExxError(token.line, "expected an assignment, binding, or procedure call")

    def _control(self) -> Stmt:
        token = self._advance()
        self._expect("(")
        condition = self._expression()
        self._expect(")")
        body = self._body()
        otherwise = ()
        if token.value == "if" and self._accept_after_newlines("else"):
            otherwise = self._body()
        return Stmt(token.value, token.line, condition, body=body, otherwise=otherwise)

    def _binding_names(self, expr: Expr) -> tuple[str, ...]:
        names = expr.args if expr.kind == "tuple" else (expr,)
        if any(name.kind != "name" or "." in name.value for name in names):
            raise ExxError(expr.line, "expected names on the left side of the binding")
        return tuple(name.value for name in names)

    def _expression(self, minimum: int = 1) -> Expr:
        left = self._primary()
        while (precedence := _PRECEDENCE.get(self.token.value, 0)) >= minimum:
            operator = self._advance()
            self._skip_newlines()
            right = self._expression(precedence + 1)
            left = Expr("binary", operator.value, (left, right), operator.line)
        return left

    def _primary(self) -> Expr:
        token = self.token
        if token.value in {"!", "+", "-"}:
            self._advance()
            return Expr("unary", token.value, (self._primary(),), token.line)
        if token.kind == "int":
            self._advance()
            radix = 0 if token.value.lower().startswith(("0x", "0b")) else 10
            return Expr("int", int(token.value, radix), (), token.line)
        if self._accept("("):
            if self._accept(")"):
                return Expr("tuple", None, (), token.line)
            item = self._expression()
            if self._accept(")"):
                return item
            self._expect(",")
            return Expr("tuple", None, (item, *self._list_tail()), token.line)
        if token.kind == "name":
            name = self._qualified_name()
            if self._accept("("):
                return Expr("call", name, self._list_tail(), token.line)
            value = Expr("name", name, (), token.line)
            while self._accept("->"):
                field = self._expect_name()
                value = Expr("field", field.value, (value,), field.line)
            return value
        raise ExxError(token.line, f"expected an expression, found {self._found()}")

    def _list_tail(self) -> tuple[Expr, ...]:
        items = []
        while not self._accept(")"):
            items.append(self._expression())
            if self._accept(")"):
                break
            self._expect(",")
        return tuple(items)


def parse(source: str) -> Program:
    """Parse EXX source, raising ExxError for invalid syntax."""
    return _Parser(_tokenize(source)).program()
