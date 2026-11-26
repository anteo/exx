"""Parse the EXX token stream into a syntax tree."""

from dataclasses import replace

from .diagnostics import ExxError
from .syntax import AsmBlock, Constant, DataSymbol, Expr, Field, Layout, Origin, Param, Proc, Program, Stmt, Struct
from .tokenizer import Token, tokenize


_ASSIGN = frozenset({"=", "^=", "+=", "-=", "&=", "|=", "<<=", ">>="})
_UPDATE = frozenset({"++", "--"})
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

    def _integer(self) -> int:
        token = self.token
        if token.kind != "int":
            raise ExxError(token.line, f"expected an integer, found {self._found()}")
        self._advance()
        radix = 0 if token.value.lower().startswith(("0x", "0b")) else 10
        return int(token.value, radix)

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
        assembly = []
        layouts = []
        structs = []
        constants = []
        origins = []
        self._skip_separators()
        while self.token.kind != "eof":
            line = self.token.line
            is_extern = self._accept("extern")
            following = self.tokens[self.index + 1] if self.token.kind != "eof" else self.token
            if self.token.value == "data" and following.kind == "name":
                data.append(self._data(is_extern))
            elif not is_extern and self.token.value == "field" and (following.kind == "name" or following.value == "{"):
                self._advance()
                self._declaration_group(lambda: self._field_entry(fields))
            elif not is_extern and self.token.value == "layout" and (following.kind == "name" or following.value == "{"):
                self._advance()
                self._declaration_group(lambda: self._layout_entry(layouts, fields))
            elif not is_extern and self.token.value == "struct" and following.kind == "name":
                self._advance()
                name = self._qualified_name()
                self._skip_newlines()
                self._expect("{")
                structs.append(Struct(name, self._members(), line))
            elif not is_extern and self.token.value == "const" and (following.kind == "name" or following.value == "{"):
                self._advance()
                self._declaration_group(lambda: constants.append(self._constant()))
            elif not is_extern and self.token.value == "origin":
                start = self._advance()
                origins.append(Origin(self._expression(), start.line, start.offset))
                self._expect_statement_end()
            elif not is_extern and self.token.value == "asm":
                assembly.append(self._assembly(file_scope=True))
            else:
                procs.append(self._procedure(is_extern, line))
            self._skip_separators()
        return Program(tuple(procs), tuple(data), tuple(fields), tuple(assembly), tuple(layouts), tuple(structs),
                       tuple(constants), tuple(origins))

    def _declaration_group(self, entry):
        if self._accept("{"):
            self._declaration_entries(entry)
        else:
            entry()
            self._expect_statement_end()

    def _declaration_entries(self, entry):
        self._skip_separators()
        while not self._accept("}"):
            entry()
            if self.token.value == "}":
                continue
            if not self._accept(",") and self.token.value != ";" and self.token.kind != "newline":
                raise ExxError(self.token.line, f"expected a declaration separator, found {self._found()}")
            self._skip_separators()

    def _members(self):
        members = []

        def member():
            name = self._expect_name()
            self._expect(":")
            members.append(Field(name.value, self._qualified_name(), name.line))

        self._declaration_entries(member)
        return tuple(members)

    def _grouped_fields(self, name, fields):
        fields.extend(replace(member, name=f"{name}.{member.name}") for member in self._members())

    def _field_entry(self, fields):
        line = self.token.line
        name = self._qualified_name()
        if self._accept_after_newlines("{"):
            self._grouped_fields(name, fields)
        else:
            if "." not in name:
                raise ExxError(line, "field declaration requires Layout.member")
            self._expect(":")
            fields.append(Field(name, self._qualified_name(), line))

    def _layout_entry(self, layouts, fields):
        line = self.token.line
        name = self._qualified_name()
        self._expect(":")
        layouts.append(Layout(name, self._integer(), line))
        if self._accept_after_newlines("{"):
            self._grouped_fields(name, fields)

    def _constant(self):
        name = self._expect_name()
        self._expect("=")
        return Constant(name.value, self._expression(), name.line, name.offset)

    def _data(self, is_extern):
        start = self._expect("data")
        name = self._expect_name()
        type_name = None
        if not is_extern or self.token.value == ":":
            self._expect(":")
            kind = self._expect_name()
            if kind.value not in ("u8", "u16"):
                raise ExxError(kind.line, "data type must be u8 or u16")
            type_name = kind.value
        initializer = None
        if not is_extern:
            self._expect("=")
            initializer = self._expression()
        self._expect_statement_end()
        return DataSymbol(name.value, start.line, type_name, initializer, start.offset)

    def _assembly(self, *, file_scope=False):
        start = self._expect("asm")
        self._skip_newlines()
        inputs = outputs = clobbers = ()
        if file_scope and self.token.value != "{":
            raise ExxError(start.line, "a file-scope asm block takes no register contract")
        if self.token.value == "(":
            inputs = self._names()
        if self._accept_after_newlines("→", "->"):
            outputs = self._names() if self.token.value == "(" else (self._expect_name().value,)
        if self._accept_after_newlines("clobbers"):
            clobbers = self._names()
        self._skip_newlines()
        self._expect("{")
        body = self._advance()
        self._expect("}")
        return AsmBlock(body.value, start.line, body.offset, inputs, outputs, clobbers)

    def _procedure(self, is_extern: bool, line: int) -> Proc:
        start = self.token.offset
        outputs = ()
        if self.token.value == "(":
            outputs = self._names()
            if len(outputs) < 2:
                raise ExxError(line, "a result tuple requires at least two names")
        elif self.token.kind == "name" and self.tokens[self.index + 1].kind == "name":
            outputs = (self._advance().value,)
        name = self._expect_name().value
        self._expect("(")
        params = []
        if not self._accept(")"):
            while True:
                params.append(self._parameter())
                if self._accept(")"):
                    break
                self._expect(",")
        frame = None
        if is_extern and self.token.value == "frame":
            raise ExxError(line, "frame belongs on the procedure definition")
        if not is_extern and self._accept_after_newlines("frame"):
            self._expect("(")
            frame = self._expect_name().value
            self._expect(")")
        clobbers = self._names() if self._accept_after_newlines("clobbers") else ()
        if is_extern:
            self._expect_statement_end()
            body = None
        else:
            self._skip_newlines()
            body = self._block()
        end = self.tokens[self.index - 1]
        return Proc(name, tuple(params), outputs, clobbers, body, line,
                    end_line=end.line, start=start, end=end.offset, frame=frame)

    def _parameter(self) -> Param:
        name = self._expect_name()
        type_name = self._qualified_name() if self._accept(":") else None
        if not (self._accept("->") or self._accept("→")):
            if type_name is None:
                raise ExxError(name.line, "a parameter requires a register binding or a stack type")
            return Param(name.value, None, type_name, name.line)
        location = self._expect_name().value
        if location != "stack":
            return Param(name.value, location, type_name, name.line)
        if type_name is None:
            raise ExxError(name.line, "a stack parameter requires a type")
        self._expect("[")
        offset = self._integer()
        self._expect("]")
        return Param(name.value, None, type_name, name.line, offset)

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
        return self._block_contents()

    def _block_contents(self) -> tuple[Stmt, ...]:
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
        start = self.token.offset
        stmt = self._statement_body()
        return replace(stmt, start=start, end=self.tokens[self.index - 1].offset)

    def _statement_body(self) -> Stmt:
        token = self.token
        if token.kind == "name" and self.tokens[self.index + 1].value == ":":
            self._advance()
            self._advance()
            return Stmt("label", token.line, token.value)
        if self._accept("goto"):
            label = self._expect_name()
            self._expect_statement_end()
            return Stmt("goto", token.line, label.value)
        if token.value == "asm":
            return Stmt("asm", token.line, self._assembly())
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
        if target.kind == "call" and target.value == "keep" and self._accept_after_newlines("{"):
            if not target.args or any(arg.kind != "name" for arg in target.args):
                raise ExxError(token.line, "keep requires register pairs or their aliases")
            return Stmt("keep", token.line, target, body=self._block_contents())
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
        if target.kind in ("call", "prefix_update", "postfix_update"):
            self._expect_statement_end()
            return Stmt(target.kind, token.line, target)
        raise ExxError(token.line, "expected an assignment, binding, register update, or procedure call")

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
        if token.value in _UPDATE:
            self._advance()
            return self._update("prefix_update", token, self._primary())
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
            value = Expr("bit", None, (value, index), token.line)
        if self.token.value in _UPDATE:
            return self._update("postfix_update", self._advance(), value)
        return value

    def _update(self, kind, token, target):
        if target.kind != "name":
            raise ExxError(token.line, f"{token.value} requires a register or register alias")
        return Expr(kind, token.value, (target,), token.line)

    def _atom(self) -> Expr:
        token = self.token
        if token.value in {"true", "false"}:
            self._advance()
            return Expr("int", int(token.value == "true"), (), token.line)
        if token.kind == "int":
            return Expr("int", self._integer(), (), token.line)
        if self._accept("("):
            if self._accept(")"):
                return Expr("tuple", None, (), token.line)
            item = self._expression()
            if self._accept("="):
                if item.kind != "name":
                    raise ExxError(item.line, "a nested assignment requires a register name")
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
            if self._accept("->"):
                while True:
                    field = self._expect_name()
                    value = Expr("field", field.value, (value,), field.line)
                    if not self._accept("."):
                        break
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


def parse(source: str, *, comments: list[Token] | None = None) -> Program:
    """Parse EXX source, raising ExxError for invalid syntax."""
    return _Parser(tokenize(source, comments=comments)).program()
