from ..emit import Assembler
from ..registry import targets


@targets.register
class PlainAsm(Assembler):
    """Assembly fragment using the platform's native operand spelling."""

    name = "asm"
    platforms = ("z80",)
