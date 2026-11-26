"""Convert EXX source text to tokens with line numbers."""

import re
from dataclasses import dataclass

from .diagnostics import ExxError


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int


_TOKEN = re.compile(
    r"(?P<space>[ \t\v\f]+)"
    r"|(?P<newline>\r\n?|\n)"
    r"|(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)"
    r"|(?P<name>[a-zA-Z_][a-zA-Z_0-9]*)"
    r"|(?P<int>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)"
    r"|(?P<punct><<=|>>=|<<|>>|->|→|\|\||&&|==|!=|<=|>=|[&|^+\-]=|[(){}:;,!+\-.^<>=&|~$])"
)
_KEYWORDS = frozenset({"extern", "clobbers", "if", "else", "while", "return", "true", "false"})


def tokenize(source: str) -> list[Token]:
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
                tokens.append(Token("newline", "\n", line))
            line += value.count("\n")
        elif kind != "space":
            if value == "(":
                parentheses += 1
            elif value == ")" and parentheses > 0:
                parentheses -= 1
            if kind == "name" and value in _KEYWORDS:
                kind = "keyword"
            tokens.append(Token(kind, value, line))
    tokens.append(Token("eof", "", line))
    return tokens
