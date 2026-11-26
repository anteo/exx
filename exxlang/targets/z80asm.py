import re

from ..emit import Assembler
from ..registry import targets


_SYMBOL = re.compile(r"(?<![\w.])[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")


@targets.register
class Z80Asm(Assembler):
    name = "z80asm"
    platforms = ("z80",)

    def header(self, procedures, section):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", section):
            raise ValueError(f"invalid {self.name} section name {section!r}")
        items = [*procedures, *getattr(procedures, "data", ())]
        local = dict.fromkeys(item.name for item in items)
        external = set().union(*(item.externals for item in items)) - local.keys()
        self.symbols = {name: name for name in (*local, *external)}
        return ["", f"    SECTION {section}",
                *(f"    PUBLIC {name}" for name in local),
                *(f"    EXTERN {name}" for name in sorted(external))]

    def operands(self, items):
        def render(match):
            name = match[0]
            spelling = name.replace(".", "_")
            previous = self.symbols.setdefault(spelling, name)
            if previous != name:
                raise ValueError(f"{self.name} symbol collision: {previous!r} and {name!r} both map to {spelling!r}")
            return spelling

        return _SYMBOL.sub(render, super().operands(items))
