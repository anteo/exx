import re

from ..emit import Assembler, structure_guard
from ..registry import targets


_SYMBOL = re.compile(r"(?<![\w.])[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")


@targets.register
class Z80Asm(Assembler):
    name = "z80asm"
    platforms = ("z80",)

    def __init__(self):
        self.symbols = {}

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

    def structure_lines(self, structures):
        definitions = {struct.name: struct for struct in structures}
        result = []

        def nested_offsets(struct, prefix, base):
            for member in struct.members:
                name = f"{prefix}.{member.name}"
                offset = base + member.offset
                yield f"    DEFC {self.operands((name,))} = {offset}"
                child = definitions.get(member.type_name)
                if child is not None:
                    yield from nested_offsets(child, name, offset)

        for struct in structures:
            guard = structure_guard(struct)
            result.extend(("", f"    IFNDEF {guard}", f"    DEFINE {guard}", "    DEFVARS 0 {"))
            for member in struct.members:
                name = self.operands((f"{struct.name}.{member.name}",))
                directive = "DS.W 1" if member.type_name == "u16" else f"DS.B {member.size}"
                result.append(f"        {name} {directive}")
            result.extend(("    }", f"    DEFC {self.operands((struct.name,))} = {struct.size}"))
            for member in struct.members:
                child = definitions.get(member.type_name)
                if child is not None:
                    result.extend(nested_offsets(child, f"{struct.name}.{member.name}", member.offset))
            result.append("    ENDIF")
        return result
