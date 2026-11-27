"""Convert EXX source text to tokens with line numbers."""

import re
from dataclasses import dataclass, field

from .diagnostics import ExxError


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    offset: int = field(default=0, compare=False)


_TOKEN = re.compile(
    r"(?P<space>[ \t\v\f]+)"
    r"|(?P<newline>\r\n?|\n)"
    r"|(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)"
    r'|(?P<string>"(?:[^"\\\r\n]|\\["\\])*")'
    r"|(?P<name>[a-zA-Z_][a-zA-Z_0-9]*)"
    r"|(?P<int>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)"
    r"|(?P<punct><<=|>>=|<<|>>|->|→|\+\+|--|\|\||&&|==|!=|<=|>=|[&|^+\-]=|[(){}\[\]*:;,!+\-.^<>=&|~$])"
)
_KEYWORDS = frozenset({"asm", "extern", "clobbers", "if", "else", "do", "while", "repeat", "break", "goto", "origin",
                       "return", "true", "false"})
_CLOSING = {"}": "{", ")": "(", "]": "["}

# Braces inside assembler strings and comments are data. The apostrophe
# in the Z80 register AF' is part of the register name.
_ASM_DELIMITER = re.compile(
    r""";[^\n]*|//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|"(?:\\[^\n]|""|[^"\\\n])*" """
    r"""|(?<![\w'])'(?:\\[^\n]|''|[^'\\\n])*'|[{}]""", re.VERBOSE,
)


def _asm_end(source, start, line):
    depth = 1
    for match in _ASM_DELIMITER.finditer(source, start):
        if match[0] == "{":
            depth += 1
        elif match[0] == "}":
            depth -= 1
            if depth == 0:
                return match.start()
    raise ExxError(line, "unterminated asm block")


def tokenize(source: str, *, comments: list[Token] | None = None) -> list[Token]:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    tokens = []
    line = 1
    groups = []
    offset = 0
    asm_header = False
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
            if kind == "comment" and comments is not None:
                comments.append(Token(kind, value, line, match.start()))
            if "\n" in value and (not groups or groups[-1] == "{"):
                tokens.append(Token("newline", "\n", line))
            line += value.count("\n")
        elif asm_header and value == "{":
            end = _asm_end(source, offset, line)
            body = source[offset:end]
            tokens.append(Token("punct", "{", line, match.start()))
            tokens.append(Token("asm_body", body, line, offset))
            line += body.count("\n")
            tokens.append(Token("punct", "}", line, end))
            offset = end + 1
            asm_header = False
        elif kind != "space":
            if value in ("(", "[", "{"):
                groups.append(value)
            elif groups and _CLOSING.get(value) == groups[-1]:
                groups.pop()
            if kind == "name" and value in _KEYWORDS:
                kind = "keyword"
                if value == "asm":
                    asm_header = True
            tokens.append(Token(kind, value, line, match.start()))
    tokens.append(Token("eof", "", line))
    return tokens
