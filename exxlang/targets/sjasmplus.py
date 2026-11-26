from ..emit import structure_guard
from ..registry import targets
from .asm import PlainAsm


@targets.register
class Sjasmplus(PlainAsm):
    name = "sjasmplus"
    local_label_prefix = "."

    def structure_lines(self, structures):
        result = []
        indent = self.indent
        names = {struct.name for struct in structures}
        for struct in structures:
            guard = structure_guard(struct)
            result.extend(("", f"{indent}IFNDEF {guard}", f"{indent}DEFINE {guard} 1",
                           f"{indent}STRUCT @{struct.name}"))
            for member in struct.members:
                if member.type_name in names:
                    directive = f"@{member.type_name}"
                else:
                    directive = {"u8": "BYTE", "u16": "WORD"}.get(member.type_name, f"BLOCK {member.size}")
                result.append(f"{member.name} {directive}")
            result.extend((f"{indent}ENDS", f"{indent}ENDIF"))
        return result
