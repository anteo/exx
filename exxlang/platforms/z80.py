"""Instruction selection and physical register effects for the Z80."""

import re
from typing import Callable

from ..ir import Instruction, Operand, TargetError
from ..registry import platforms


FLAGS = frozenset(("CF", "Z", "S", "PV", "HF", "N"))
BYTE_REGISTERS = frozenset(("A", "B", "C", "D", "E", "H", "L"))
WORD_PARTS = {
    "AF": frozenset(("A",)) | FLAGS,
    "BC": frozenset(("B", "C")),
    "DE": frozenset(("D", "E")),
    "HL": frozenset(("H", "L")),
    "IX": frozenset(("IX",)),
    "IY": frozenset(("IY",)),
    "SP": frozenset(("SP",)),
}
LOAD_WORDS = frozenset(("BC", "DE", "HL", "IX", "IY", "SP"))
INDEX_REGISTERS = frozenset(("IX", "IY"))
UNSUPPORTED_REGISTERS = frozenset({
    "I", "R", "IXH", "IXL", "IYH", "IYL", "IXU", "IYU", "XH", "XL", "YH", "YL",
    "HX", "LX", "HY", "LY",
})
CONDITION_FLAGS = {"c": "CF", "nc": "CF", "z": "Z", "nz": "Z",
                   "m": "S", "p": "S", "pe": "PV", "po": "PV"}
FLAG_CONDITIONS = {"CF": ("c", "nc"), "Z": ("z", "nz"),
                   "S": ("m", "p"), "PV": ("pe", "po")}
INVERSE_CONDITION = {
    condition: inverse
    for pair in FLAG_CONDITIONS.values()
    for condition, inverse in (pair, pair[::-1])
}
COMPARISONS = {
    "==": "z", "!=": "nz", "<": "c", ">=": "nc",
}
REVERSED = {"==": "==", "!=": "!=", "<": ">", ">": "<", "<=": ">=", ">=": "<="}
NEGATED = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", "<=": ">", ">": "<="}


def register(name: str) -> Operand | None:
    if name in BYTE_REGISTERS or name == "F":
        return Operand("reg", name, 8)
    if name in WORD_PARTS:
        return Operand("reg", name, 16)
    if name in FLAGS:
        return Operand("flag", name, 1)
    return None


def resources(name: str) -> frozenset[str]:
    if name == "F":
        return FLAGS
    if name in WORD_PARTS:
        return WORD_PARTS[name]
    if name in BYTE_REGISTERS or name in FLAGS:
        return frozenset((name,))
    return frozenset()


def supports_layout(reg: str) -> bool:
    return reg in INDEX_REGISTERS


def field_operand(reg: str, layout: str, field: str) -> Operand:
    if not supports_layout(reg):
        raise TargetError(f"{reg} cannot address a structure field on Z80")
    return Operand("mem", f"{reg} + {layout}.{field}", 8)


def _literal(text: str) -> int | None:
    try:
        return int(text, 0)
    except ValueError:
        return None


def _indirect(operand: Operand) -> tuple[str | None, str]:
    text = operand.text.strip()
    for name in ("HL", "BC", "DE", "IX", "IY", "SP"):
        if text.upper() == name:
            return name, name.lower() + (" + 0" if name in INDEX_REGISTERS else "")
        if name in INDEX_REGISTERS and text[:2].upper() == name:
            displacement = text[2:].lstrip()
            if displacement[:1] in ("+", "-"):
                literal = _literal(displacement[1:].strip())
                if literal is not None and displacement[0] == "-":
                    literal = -literal
                if literal is not None and not -128 <= literal <= 127:
                    raise TargetError(f"invalid Z80 index displacement {literal}")
                return name, f"{name.lower()} {displacement[0]} {displacement[1:].strip()}"
    return None, text


def _text(operand: Operand) -> str:
    if operand.kind == "mem":
        return f"({_indirect(operand)[1]})"
    if operand.kind in ("reg", "flag"):
        return operand.text.lower()
    if operand.kind == "imm" and operand.text.startswith("("):
        # Both assemblers interpret LD A,(expression) as a memory read.
        return "0 + " + operand.text
    return operand.text


def _reads(operand: Operand) -> frozenset[str]:
    if operand.kind in ("reg", "flag"):
        return resources(operand.text)
    if operand.kind == "mem":
        base, _ = _indirect(operand)
        return resources(base) if base else frozenset()
    return frozenset()


def _validate_immediate(operand: Operand, width: int) -> None:
    value = _literal(operand.text)
    if value is not None and not -(1 << (width - 1)) <= value < 1 << width:
        raise TargetError(f"immediate {operand.text} does not fit in {width} bits")


def _ld(dst: Operand, src: Operand) -> tuple[Instruction, ...]:
    if src.kind == "imm":
        _validate_immediate(src, dst.width)
    reads = _reads(src) | (_reads(dst) if dst.kind == "mem" else frozenset())
    writes = resources(dst.text) if dst.kind == "reg" else frozenset()
    return (Instruction("ld", (_text(dst), _text(src)), reads, writes),)


def _byte_load(dst: Operand, src: Operand) -> bool:
    if any(operand.kind == "reg" and operand.text not in BYTE_REGISTERS for operand in (dst, src)):
        return False
    if dst.kind == "reg" and src.kind in ("reg", "imm"):
        return True
    if dst.kind == "reg" and src.kind == "mem":
        base, _ = _indirect(src)
        return base in ("HL", "IX", "IY") or (dst.text == "A" and base != "SP")
    if dst.kind == "mem" and src.kind in ("reg", "imm"):
        base, _ = _indirect(dst)
        return base in ("HL", "IX", "IY") or (src.text == "A" and base != "SP")
    return False


def _word_load(dst: Operand, src: Operand) -> bool:
    if dst.kind == "reg" and dst.text in LOAD_WORDS:
        if src.kind == "imm":
            return True
        if src.kind == "mem":
            return _indirect(src)[0] is None
        return dst.text == "SP" and src.kind == "reg" and src.text in ("HL", "IX", "IY")
    if dst.kind == "mem" and src.kind == "reg" and src.text in LOAD_WORDS:
        return _indirect(dst)[0] is None
    return False


def move(dst: Operand, src: Operand) -> tuple[Instruction, ...]:
    if dst == src and dst.kind in ("reg", "flag"):
        return ()
    if dst.kind == "flag":
        value = _literal(src.text) if src.kind == "imm" else None
        if dst.text == "CF" and value in (0, 1):
            effects = frozenset(("CF", "HF", "N"))
            set_carry = Instruction("scf", writes=effects)
            if value == 1:
                return (set_carry,)
            return (set_carry, Instruction("ccf", reads=frozenset(("CF",)), writes=effects))
    elif src.kind != "flag" and (src.kind == "imm" or dst.width == src.width):
        if dst.width == 8 and _byte_load(dst, src):
            return _ld(dst, src)
        if dst.width == 16 and _word_load(dst, src):
            return _ld(dst, src)
    raise TargetError(f"cannot assign {src.text} to {dst.text} on Z80")


def constant_return(
    outputs: tuple[str, ...],
    values: tuple[Operand, ...],
    writable: frozenset[str],
) -> tuple[Instruction, ...] | None:
    affected = FLAGS | {"A"}
    if outputs != ("CF", "A") or len(values) != 2 or affected - writable:
        return None
    carry, result = (
        _literal(value.text) if value.kind == "imm" else None for value in values
    )
    if carry != 0 or result not in (0, 1):
        return None

    # Self-XOR always produces zero, so the old value of A is irrelevant.
    clear_a = Instruction("xor", ("a",), writes=affected)
    if result == 0:
        return (clear_a,)
    increment = Instruction("inc", ("a",), resources("A"), affected - {"CF"})
    return clear_a, increment


def _alu_source(src: Operand) -> bool:
    if src.kind == "imm":
        _validate_immediate(src, 8)
        return True
    if src.width != 8:
        return False
    if src.kind == "reg":
        return src.text in BYTE_REGISTERS
    if src.kind == "mem":
        return _indirect(src)[0] in ("HL", "IX", "IY")
    return False


def binary(dst: Operand, op: str, src: Operand) -> tuple[Instruction, ...]:
    op = op.removesuffix("=")
    alu = {"+": "add", "-": "sub", "^": "xor", "&": "and", "|": "or"}
    if dst.kind == "reg" and dst.text == "A" and op in alu and _alu_source(src):
        operands = ("a", _text(src)) if op == "+" else (_text(src),)
        reads = _reads(dst) | _reads(src)
        return (Instruction(alu[op], operands, reads, resources("A") | FLAGS),)
    if op in ("+", "-") and src.kind == "imm" and _literal(src.text) == 1:
        inc_dec = "inc" if op == "+" else "dec"
        is_byte = _alu_source(dst) and dst.kind in ("reg", "mem")
        is_word = dst.kind == "reg" and dst.text in LOAD_WORDS
        if is_byte or is_word:
            writes = resources(dst.text) if dst.kind == "reg" else frozenset()
            if is_byte:
                writes |= FLAGS - {"CF"}
            return (Instruction(inc_dec, (_text(dst),), _reads(dst), writes),)
    if op == "+" and dst.kind == src.kind == "reg" and dst.text in ("HL", "IX", "IY"):
        if src.text in ("BC", "DE", "SP", dst.text):
            reads = _reads(dst) | _reads(src)
            writes = resources(dst.text) | {"CF", "HF", "N"}
            return (Instruction("add", (_text(dst), _text(src)), reads, writes),)
    raise TargetError(f"cannot generate {dst.text} {op}= {src.text} on Z80 without a temporary")


def _jump(condition: str, label: str) -> Instruction:
    return Instruction("jp", (condition, label), resources(CONDITION_FLAGS[condition]),
                       branch_target=label)


def jump(label: str) -> Instruction:
    return Instruction("jp", (label,), branch_target=label, falls_through=False)


def branch(
    left: Operand,
    relation: str | None,
    right: Operand | None,
    label: str,
    when_true: bool = True,
    *,
    new_label: Callable[[], str] | None = None,
) -> tuple[Instruction, ...]:
    if relation is None:
        if left.kind == "flag":
            if left.text not in FLAG_CONDITIONS:
                raise TargetError(f"Z80 cannot branch directly on {left.text}")
            true_condition, false_condition = FLAG_CONDITIONS[left.text]
            return (_jump(true_condition if when_true else false_condition, label),)
        relation = "!="
        right = Operand("imm", "0")
    if relation not in REVERSED or right is None:
        raise TargetError(f"unsupported Z80 condition {relation}")
    if right == register("A"):
        left, right = right, left
        relation = REVERSED[relation]
    if left != register("A") or not _alu_source(right):
        raise TargetError(f"Z80 comparison requires an accumulator operand: {left.text} {relation} {right.text}")
    if not when_true:
        relation = NEGATED[relation]
    if right.kind == "imm" and _literal(right.text) == 0 and relation in ("==", "!="):
        compare = Instruction("or", ("a",), resources("A"), FLAGS)
    else:
        compare = Instruction("cp", (_text(right),), resources("A") | _reads(right), FLAGS)
    if relation == "<=":
        return compare, _jump("c", label), _jump("z", label)
    if relation == ">":
        if new_label is None:
            raise TargetError("generating this Z80 condition requires an additional label")
        skip = new_label()
        return compare, _jump("c", skip), _jump("nz", label), Instruction("label", (skip,))
    return compare, _jump(COMPARISONS[relation], label)


def compact(code: list[Instruction]) -> tuple[Instruction, ...]:
    """Fold short control-flow patterns after the ABI analysis."""
    compacted: list[Instruction] = []
    index = 0
    while index < len(code):
        instruction = code[index]
        index += 1
        if instruction.mnemonic != "jp":
            compacted.append(instruction)
            continue

        next_index = index
        can_fold_return = (
            len(instruction.operands) == 2
            and instruction.operands[0] in INVERSE_CONDITION
            and index < len(code)
            and code[index].mnemonic == "ret"
            and not code[index].operands
        )
        if can_fold_return:
            next_index += 1

        target = instruction.operands[-1]
        while next_index < len(code) and code[next_index].mnemonic == "label":
            if code[next_index].operands[0] == target:
                break
            next_index += 1
        if next_index == len(code) or code[next_index].mnemonic != "label":
            compacted.append(instruction)
        elif can_fold_return:
            condition = INVERSE_CONDITION[instruction.operands[0]]
            ret = code[index]
            compacted.append(Instruction("ret", (condition,), instruction.reads | ret.reads))
            index += 1

    # EXX reserves these labels for internal jumps. Match symbolic operands too,
    # so a label still used in an address expression survives compaction.
    referenced = {
        name.lower()
        for instruction in compacted
        if instruction.mnemonic != "label"
        for operand in instruction.operands
        for name in re.findall(r"\bexx__\w+", operand, re.IGNORECASE)
    }
    return tuple(
        instruction
        for instruction in compacted
        if instruction.mnemonic != "label"
        or not instruction.operands[0].lower().startswith("exx__")
        or instruction.operands[0].lower() in referenced
    )


@platforms.register
class Z80:
    name = "z80"
    reserved_abi = {"SP": "SP is reserved for balanced procedure calls"}
    unsupported_registers = UNSUPPORTED_REGISTERS
    layout_registers = tuple(sorted(INDEX_REGISTERS))
    register = staticmethod(register)
    resources = staticmethod(resources)
    field_operand = staticmethod(field_operand)
    operand_reads = staticmethod(_reads)
    move = staticmethod(move)
    binary = staticmethod(binary)
    branch = staticmethod(branch)
    jump = staticmethod(jump)
    constant_return = staticmethod(constant_return)
    compact = staticmethod(compact)

    def call(self, name, inputs, outputs, tail):
        return Instruction("jp" if tail else "call", (name,), inputs, outputs, falls_through=not tail)

    def ret(self, outputs=frozenset()):
        return Instruction("ret", reads=outputs, falls_through=False)
