"""Choose Z80 branch encodings after all procedure bodies have been lowered."""

from dataclasses import replace

from ..ir import Instruction
from ..syntax import AsmBlock


_JR_CONDITIONS = {"nz", "z", "nc", "c"}
_FIXED_SIZES = {"label": 0, "ret": 1, "cpl": 1, "scf": 1, "ccf": 1, "ex": 1,
                "exx": 1, "in": 2, "out": 2, "jp": 3, "call": 3}


def _long_repeat(ins):
    target = ins.branch_target
    again, done = target + "_again", target + "_done"
    return (
        replace(ins, operands=(again,), branch_target=again),
        Instruction("jr", (done,), branch_target=done, falls_through=False),
        Instruction("label", (again,)),
        Instruction("jp", (target,), branch_target=target, falls_through=False),
        Instruction("label", (done,)),
    )


def relax_branches(module):
    code = []
    bodies = []
    for item in sorted([*module, *module.assembly], key=lambda item: item.start):
        if isinstance(item, AsmBlock):
            code.append(Instruction("asm"))
            continue
        code.append(Instruction("label", (item.name,)))
        start = len(code)
        code.extend(item.instructions)
        bodies.append((item, start, len(code)))

    labels = {ins.operands[0]: i for i, ins in enumerate(code) if ins.mnemonic == "label"}
    sizes = [ins.encoded_size if ins.encoded_size is not None else _FIXED_SIZES.get(ins.mnemonic)
             for ins in code]
    branches = {}
    for i, ins in enumerate(code):
        if ins.mnemonic == "djnz" or (ins.mnemonic in ("jp", "jr") and
                (len(ins.operands) == 1 or ins.operands[0] in _JR_CONDITIONS)):
            sizes[i] = 2
            branches[i] = labels.get(ins.operands[-1])

    # Start with short encodings. Widening can push other edges out of
    # range, but cannot bring a previously rejected edge back into range.
    while branches:
        offsets = []
        regions = []
        offset = region = 0
        for size in sizes:
            offsets.append(offset)
            regions.append(region)
            if size is None:  # Raw assembly or an instruction of unknown size.
                region += 1
                offset = 0
            else:
                offset += size
        rejected = [i for i, target in branches.items()
                    if target is None or regions[i] != regions[target]
                    or not -128 <= offsets[target] - (offsets[i] + 2) <= 127]
        if not rejected:
            break
        for i in rejected:
            sizes[i] = 7 if code[i].mnemonic == "djnz" else 3
            del branches[i]

    for procedure, start, end in bodies:
        result = []
        for i in range(start, end):
            ins = code[i]
            if ins.mnemonic == "djnz" and i not in branches:
                result.extend(_long_repeat(ins))
            elif ins.mnemonic in ("jp", "jr"):
                result.append(replace(ins, mnemonic="jr" if i in branches else "jp"))
            else:
                result.append(ins)
        procedure.instructions = tuple(result)
