"""Instruction selection and physical register effects for the Z80."""

import re
from typing import Callable

from ..ir import Instruction, Operand, TargetError, Transfer
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
SHADOW_PAIRS = ("AF", "BC", "DE", "HL")
for _pair in SHADOW_PAIRS:
    WORD_PARTS[_pair + "_ALT"] = frozenset(part + "_ALT" for part in WORD_PARTS[_pair])

# Stack transfers may reinterpret a word as a different pair. Track each bit
# so partial inputs, the six documented flags and index registers survive this.
STORAGE = {name: tuple((name, i) for i in range(width))
           for group, width in ((BYTE_REGISTERS, 8), (FLAGS, 1), (("IX", "IY", "SP"), 16))
           for name in group}
for _part in BYTE_REGISTERS | FLAGS:
    STORAGE[_part + "_ALT"] = tuple((_part + "_ALT", i) for _, i in STORAGE[_part])


def _word_cells(name):
    if name in INDEX_REGISTERS:
        return STORAGE[name]
    pair = name.removesuffix("_ALT")
    suffix = name[len(pair):]
    if pair == "AF":
        # F bits 3 and 5 have no portable value in the EXX ABI.
        flags = ("CF", "N", "PV", None, "HF", None, "Z", "S")
        low = tuple(STORAGE[f + suffix][0] if f else None for f in flags)
    else:
        low = STORAGE[pair[1] + suffix]
    return low + STORAGE[pair[0] + suffix]
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


def field_operand(reg: str, layout: str, field: str, width: int = 8) -> Operand:
    if not supports_layout(reg):
        raise TargetError(f"{reg} cannot address a structure field on Z80")
    return Operand("mem", f"{reg} + {layout}.{field}", width)


def indirect_operand(base, offset=None):
    if base.kind != "reg" or base.text not in ("BC", "DE", "HL", "IX", "IY"):
        raise TargetError("byte dereference requires BC, DE, HL, IX or IY")
    if offset is None:
        return Operand("mem", base.text, 8)
    if base.text not in INDEX_REGISTERS or offset.kind != "imm":
        raise TargetError("indexed access requires IX or IY and a constant displacement")
    value = _literal(offset.text)
    if value is not None and not -128 <= value <= 127:
        raise TargetError(f"invalid Z80 index displacement {value}")
    displacement = f"- {-value}" if value is not None and value < 0 else f"+ {offset.text}"
    return Operand("mem", f"{base.text} {displacement}", 8)


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
    if operand.width > width:
        raise TargetError(f"{operand.text} does not fit in {width} bits")
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


def _field_word_move(dst, src):
    store = dst.kind == "mem"
    memory, value = (dst, src) if store else (src, dst)
    low = Operand("mem", memory.text, 8)
    high = Operand("mem", memory.text + " + 1", 8)
    if value.kind == "reg" and value.text in ("BC", "DE", "HL"):
        lo, hi = register(value.text[1]), register(value.text[0])
    elif store and value.kind == "imm":
        _validate_immediate(value, 16)
        number = _literal(value.text)
        lo = Operand("imm", str(number & 255) if number is not None else f"(({value.text}) & 255)")
        hi = Operand("imm", str((number >> 8) & 255) if number is not None else f"((({value.text}) >> 8) & 255)")
    else:
        raise TargetError("u16 indexed fields require BC, DE or HL, or a constant to store")
    if store:
        return _ld(low, lo) + _ld(high, hi)
    return _ld(lo, low) + _ld(hi, high)


def move(dst: Operand, src: Operand) -> tuple[Instruction, ...]:
    for operand in (dst, src):
        if operand.kind == "mem" and operand.width == 16 and _indirect(operand)[0] in INDEX_REGISTERS:
            return _field_word_move(dst, src)
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
    if op in ("<<", ">>"):
        return shift(dst, op, src)
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


def _byte_location(operand: Operand) -> bool:
    return operand.kind in ("reg", "mem") and _alu_source(operand)


def bit_instruction(mnemonic, location, index):
    if not _byte_location(location) or index.kind != "imm":
        raise TargetError("bit access requires a byte register or indexed byte and a constant bit index")
    value = _literal(index.text)
    if value is not None and not 0 <= value <= 7:
        raise TargetError("bit index must be in 0..7")
    writes = FLAGS - {"CF"} if mnemonic == "bit" else resources(location.text)
    return Instruction(mnemonic, (_text(index), _text(location)), _reads(location), writes)


def bit_branch(location, index, label, truth):
    return bit_instruction("bit", location, index), _jump("nz" if truth else "z", label)


def bit_store(location, index, value):
    if value.kind != "imm" or value.text not in ("0", "1"):
        raise TargetError("assign true, false, 1 or 0 to a bit")
    return (bit_instruction("set" if value.text == "1" else "res", location, index),)


def complement(dst, src):
    if dst != src or dst != register("A"):
        raise TargetError("byte complement requires A = ~A")
    return (Instruction("cpl", reads=resources("A"), writes=resources("A") | {"HF", "N"}),)


_SHIFT_MNEMONICS = {"sra", "rlc", "rrc", "rl", "rr"}


def shift(location, operation, count):
    n = _literal(count.text) if count.kind == "imm" else None
    if n is None or not 0 <= n <= 255:
        raise TargetError("shift or rotation count must be a known integer in 0..255")
    if operation == "<<" and location == register("HL"):
        instruction, = binary(location, "+", location)
    elif _byte_location(location):
        mnemonic = {"<<": "sla", ">>": "srl"}.get(operation, operation)
        reads = _reads(location)
        if mnemonic in ("rl", "rr"):
            reads |= {"CF"}
        instruction = Instruction(mnemonic, (_text(location),), reads, resources(location.text) | FLAGS)
    else:
        raise TargetError(f"unsupported shift or rotation of {location.text}")
    return (instruction,) * n


def update_intrinsic(name, operands):
    if name in _TRANSFER_NAMES:
        return _transfer(name, operands)
    if name in _BLOCK_OPS:
        required, writes, invalidates = _BLOCK_OPS[name]
        if operands and operands != tuple(register(r) for r in required):
            raise TargetError(f"expected {name}() or {name}({', '.join(required)})")
        reads = frozenset().union(*(resources(r) for r in required))
        return (Instruction(name, reads=reads, writes=writes, invalidates=invalidates),)
    if name == "out" and len(operands) == 2:
        port, value = operands
        return _port_instruction(False, value, port)
    if name in _SHIFT_MNEMONICS and len(operands) in (1, 2):
        count = operands[1] if len(operands) == 2 else Operand("imm", "1")
        return shift(operands[0], name, count)
    if name in ("adc", "sbc") and len(operands) == 2:
        dst, src = operands
        if ((dst == register("A") and _alu_source(src))
                or (dst == register("HL") and src.kind == "reg" and src.text in ("BC", "DE", "HL", "SP"))):
            return (Instruction(name, (_text(dst), _text(src)), _reads(dst) | _reads(src) | {"CF"},
                                resources(dst.text) | FLAGS),)
    raise TargetError(f"invalid operands for {name}")


_TRANSFER_NAMES = {"push", "pop", "ex", "exx", "ex_sp"}
_STACK_PAIRS = {"AF", "BC", "DE", "HL", "IX", "IY"}


def _transfer(name, operands):
    names = tuple(op.text for op in operands if op.kind == "reg")
    if len(names) != len(operands):
        raise TargetError(f"{name} requires register pairs")
    if len(names) == 1 and names[0] in _STACK_PAIRS:
        word, = names
        if name in ("push", "pop"):
            return (Instruction(name, (word.lower(),), transfer=Transfer(name, _word_cells(word))),)
        if name == "ex_sp" and word in ("HL", "IX", "IY"):
            return (Instruction("ex", ("(sp)", word.lower()), transfer=Transfer("swap_stack", _word_cells(word))),)
    if name == "ex" and names in (("DE", "HL"), ("HL", "DE")):
        return (Instruction("ex", ("de", "hl"), transfer=Transfer("swap", _word_cells("DE"), _word_cells("HL"))),)
    if (name == "ex" and names == ("AF",)) or (name == "exx" and not names):
        pairs = names or ("BC", "DE", "HL")
        active = tuple(cell for word in pairs for cell in _word_cells(word))
        shadow = tuple(cell for word in pairs for cell in _word_cells(word + "_ALT"))
        op = Transfer("swap", active, shadow)
        return (Instruction(name, ("af", "af'") if name == "ex" else (), transfer=op),)
    raise TargetError(f"unsupported register combination for {name}")


def _port_instruction(read, data, port):
    if data.kind != "reg" or data.text not in BYTE_REGISTERS:
        raise TargetError("port I/O requires a byte register")
    if port == register("BC"):
        address, reads = "(c)", resources("BC")
        flags = FLAGS - {"CF"}
    elif port.kind == "imm" and data == register("A"):
        _validate_immediate(port, 8)
        address, reads = f"({_text(port)})", resources("A")
        flags = frozenset()
    else:
        raise TargetError("port I/O requires BC, or an immediate low port byte with A")
    if read:
        return (Instruction("in", (_text(data), address), reads, resources(data.text) | flags),)
    return (Instruction("out", (address, _text(data)), reads | resources(data.text)),)


def load_intrinsic(name, dst, operands):
    if name == "in" and len(operands) == 1:
        return _port_instruction(True, dst, operands[0])
    raise TargetError(f"invalid operands for {name}")


_BLOCK_OPS = {}
for _arguments, _writes, _unknown, _mnemonics in (
    (("DE", "HL", "BC"), resources("DE") | resources("HL") | resources("BC") | {"HF", "PV", "N"},
     frozenset(), ("ldi", "ldir", "ldd", "lddr")),
    (("HL", "A", "BC"), resources("HL") | resources("BC") | (FLAGS - {"CF"}),
     frozenset(), ("cpi", "cpir", "cpd", "cpdr")),
    (("HL", "C", "B"), resources("HL") | {"B", "Z"},
     FLAGS - {"Z"}, ("ini", "inir", "ind", "indr")),
    (("C", "HL", "B"), resources("HL") | {"B", "Z"},
     FLAGS - {"Z"}, ("outi", "otir", "outd", "otdr")),
):
    for _opcode in _mnemonics:
        _BLOCK_OPS[_opcode] = _arguments, _writes, _unknown


def jump(label: str) -> Instruction:
    return Instruction("jp", (label,), branch_target=label, falls_through=False)


def repeat_branch(counter, label):
    if counter != register("B"):
        raise TargetError("repeat requires B or an alias bound to B")
    return Instruction("djnz", (label,), resources("B"), resources("B"), branch_target=label)


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


def _relax_repeat_edges(code):
    # DJNZ is PC-relative. Bound distances in emitted order so widening an
    # inner loop is reflected in the distance for every enclosing loop.
    labels = {}
    position = 0
    for ins in code:
        if ins.mnemonic == "label":
            labels[ins.operands[0]] = position
        elif ins.mnemonic == "djnz":
            target = ins.branch_target
            if position + 2 - labels[target] > 128:
                again, done = target + "_again", target + "_done"
                yield Instruction("djnz", (again,), ins.reads, ins.writes, branch_target=again)
                yield jump(done)
                yield Instruction("label", (again,))
                yield jump(target)
                yield Instruction("label", (done,))
                position += 8
                continue
            position += 2
        else:
            position += 4  # Maximum encoded length of one instruction selected here.
        yield ins


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
    return tuple(_relax_repeat_edges(
        instruction
        for instruction in compacted
        if instruction.mnemonic != "label"
        or not instruction.operands[0].lower().startswith("exx__")
        or instruction.operands[0].lower() in referenced
    ))


@platforms.register
class Z80:
    name = "z80"
    reserved_abi = {"SP": "SP is reserved for balanced procedure calls"}
    unsupported_registers = UNSUPPORTED_REGISTERS
    layout_registers = tuple(sorted(INDEX_REGISTERS))
    storage_layout = STORAGE
    register = staticmethod(register)
    resources = staticmethod(resources)
    field_operand = staticmethod(field_operand)
    indirect_operand = staticmethod(indirect_operand)
    operand_reads = staticmethod(_reads)
    move = staticmethod(move)
    binary = staticmethod(binary)
    bit_branch = staticmethod(bit_branch)
    bit_store = staticmethod(bit_store)
    complement = staticmethod(complement)
    update_names = _SHIFT_MNEMONICS | {"adc", "sbc", "out"} | _TRANSFER_NAMES | _BLOCK_OPS.keys()
    load_names = {"in"}
    load_intrinsic = staticmethod(load_intrinsic)
    update_intrinsic = staticmethod(update_intrinsic)
    branch = staticmethod(branch)
    jump = staticmethod(jump)
    repeat_branch = staticmethod(repeat_branch)
    constant_return = staticmethod(constant_return)
    compact = staticmethod(compact)

    def call(self, name, inputs, outputs, tail):
        return Instruction("jp" if tail else "call", (name,), inputs, outputs, falls_through=not tail)

    def ret(self, outputs=frozenset()):
        return Instruction("ret", reads=outputs, falls_through=False)
