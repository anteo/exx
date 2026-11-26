from ..emit import structure_guard
from ..registry import targets
from .asm import PlainAsm


@targets.register
class Sjasmplus(PlainAsm):
    name = "sjasmplus"

    def structure_lines(self, structures):
        result = []
        names = {struct.name for struct in structures}
        for struct in structures:
            guard = structure_guard(struct)
            result.extend(("", f"    IFNDEF {guard}", f"    DEFINE {guard} 1", f"    STRUCT @{struct.name}"))
            for member in struct.members:
                if member.type_name in names:
                    directive = f"@{member.type_name}"
                else:
                    directive = {"u8": "BYTE", "u16": "WORD"}.get(member.type_name, f"BLOCK {member.size}")
                result.append(f"{member.name} {directive}")
            result.extend(("    ENDS", "    ENDIF"))
        return result
