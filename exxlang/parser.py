"""Parse the EXX token stream into a syntax tree."""

from .diagnostics import ExxError
from .syntax import DataSymbol, Expr, Field, Param, Proc, Program, Stmt
from .tokenizer import Token, tokenize


_ASSIGN = frozenset({"=", "^=", "+=", "-=", "&=", "|=", "<<=", ">>="})
_PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6,
    "<": 7, "<=": 7, ">": 7, ">=": 7,
    "<<": 8, ">>": 8,
    "+": 9, "-": 9,
}


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    @property
    def token(self) -> Token:
        return self.tokens[self.index]

    def _advance(self) -> Token:
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

    def _expect(self, value: str) -> Token:
        if self.token.value == value:
            return self._advance()
        raise ExxError(self.token.line, f"expected {value!r}, found {self._found()}")

    def _expect_name(self) -> Token:
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
        data = []
        fields = []
        self._skip_separators()
        while self.token.kind != "eof":
            line = self.token.line
            is_extern = self._accept("extern")
            if is_extern and self.token.value == "data" and self.tokens[self.index + 1].kind == "name":
                self._advance()
                data.append(DataSymbol(self._expect_name().value, line))
                self._expect_statement_end()
            elif not is_extern and self.token.value == "field" and self.tokens[self.index + 1].kind == "name":
                self._advance()
                name = self._qualified_name()
                if "." not in name:
                    raise ExxError(line, "field declaration requires Layout.member")
                self._expect(":")
                kind = self._expect_name().value
                if kind not in ("u8", "u16"):
                    raise ExxError(line, "field type must be u8 or u16")
                fields.append(Field(name, 8 if kind == "u8" else 16, line))
                self._expect_statement_end()
            else:
                procs.append(self._procedure(is_extern, line))
            self._skip_separators()
        return Program(tuple(procs), tuple(data), tuple(fields))

    def _procedure(self, is_extern: bool, line: int) -> Proc:
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
        if token.value in {"if", "while", "repeat"}:
            return self._control()
        if self._accept("break"):
            self._expect_statement_end()
            return Stmt("break", token.line)
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
        if token.value in {"!", "~", "+", "-", "*", "&"}:
            self._advance()
            return Expr("unary", token.value, (self._primary(),), token.line)
        value = self._atom()
        while self._accept("["):
            index = self._expression()
            self._expect("]")
            value = Expr("index", None, (value, index), token.line)
        if self._accept("$"):
            index = self._atom()
            return Expr("bit", None, (value, index), token.line)
        return value

    def _atom(self) -> Expr:
        token = self.token
        if token.value in {"true", "false"}:
            self._advance()
            return Expr("int", int(token.value == "true"), (), token.line)
        if token.kind == "int":
            self._advance()
            radix = 0 if token.value.lower().startswith(("0x", "0b")) else 10
            return Expr("int", int(token.value, radix), (), token.line)
        if self._accept("("):
            if self._accept(")"):
                return Expr("tuple", None, (), token.line)
            item = self._expression()
            if self._accept("="):
                if item.kind != "name":
                    raise ExxError(item.line, "a condition assignment requires a register name")
                value = self._expression()
                self._expect(")")
                return Expr("assign", "=", (item, value), token.line)
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
    return _Parser(tokenize(source)).program()
