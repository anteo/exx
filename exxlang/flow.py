"""Definite assignment and preservation of register contents across control flow."""

from dataclasses import dataclass

from .diagnostics import ExxError


@dataclass(frozen=True)
class Value:
    # An opaque caller value can be saved and restored without being a declared input.
    origin: object
    available: bool
    # Saved locations whose bits still equal this value on every incoming path.
    saved: frozenset = frozenset()

    def meet(self, other):
        return Value(self.origin if self.origin == other.origin else None,
                     self.available and other.available, self.saved & other.saved)


UNKNOWN = Value(None, False)
DEFINED = Value(None, True)


@dataclass(frozen=True)
class StackWord:
    values: tuple
    keep_slot: int | None

    def meet(self, other, line):
        if self.keep_slot != other.keep_slot:
            raise ExxError(line, "different keep saves at control-flow join")
        return StackWord(tuple(a.meet(b) for a, b in zip(self.values, other.values)), self.keep_slot)


@dataclass
class Flow:
    registers: dict
    stack: tuple

    @classmethod
    def entry(cls, layout, inputs):
        return cls({cell: Value(cell, name in inputs)
                    for name, cells in layout.items() for cell in cells}, ())

    def merge(self, other, line):
        if len(self.stack) != len(other.stack):
            raise ExxError(line, "different stack depths at control-flow join")
        stack = tuple(left.meet(right, line) for left, right in zip(self.stack, other.stack))
        registers = {key: value.meet(other.registers[key]) for key, value in self.registers.items()}
        return Flow(registers, stack)

    def advance(self, step, layout, protected, exit_path):
        ins = step.instruction
        missing = [name for name in ins.reads
                   if not all(self.registers[c].available for c in layout[name])]
        if missing:
            raise ExxError(step.line, f"{', '.join(sorted(missing))} unavailable (uninitialized or clobbered)")
        registers = self.registers.copy()
        stack = self.stack
        for name in step.kills | ins.invalidates:
            registers.update((c, UNKNOWN) for c in layout[name])
        for name in ins.writes:
            registers.update((c, DEFINED) for c in layout[name])
        op = ins.transfer
        if op:
            def read(cells):
                return tuple(self.registers.get(c, UNKNOWN) for c in cells)

            def write(cells, values):
                registers.update((c, v) for c, v in zip(cells, values) if c is not None)

            if op.kind == "swap":
                write(op.first, read(op.second))
                write(op.second, read(op.first))
            elif op.kind == "push":
                stack += (StackWord(read(op.first), step.keep_slot),)
                if step.keep_slot is not None:
                    for cell in op.first:
                        if cell is not None:
                            v = registers[cell]
                            registers[cell] = Value(v.origin, v.available, v.saved | {(step.keep_slot, cell)})
            elif op.kind in ("pop", "swap_stack"):
                if not stack:
                    raise ExxError(step.line, "stack operation requires a saved word")
                word = stack[-1]
                if word.keep_slot != step.keep_slot:
                    raise ExxError(step.line, "manual stack operations must balance above the keep save")
                if step.keep_slot is not None:
                    for name in sorted(step.keep_live):
                        if any((step.keep_slot, c) not in registers[c].saved for c in layout[name]):
                            raise ExxError(step.line, f"keep restoration would overwrite live {name}")
                    # A loop may enter the same keep again. Discard this activation's
                    # identities wherever its body moved them before reusing the slot.
                    for cell, v in registers.items():
                        if v.saved:
                            remaining = frozenset(tag for tag in v.saved if tag[0] != step.keep_slot)
                            registers[cell] = Value(v.origin, v.available, remaining)
                write(op.first, word.values)
                stack = stack[:-1]
                if op.kind == "swap_stack":
                    stack += (StackWord(read(op.first), None),)
            else:
                raise ValueError(f"unknown transfer {op.kind}")
        if exit_path and stack:
            raise ExxError(step.line, "unbalanced stack at procedure exit")
        displaced = {c for c in protected if registers[c].origin != c}
        if displaced and not exit_path:
            displaced.difference_update(v.origin for v in registers.values())
            displaced.difference_update(v.origin for word in stack for v in word.values)
        if displaced:
            names = sorted({protected[c] for c in displaced})
            raise ExxError(step.line, f"undeclared clobber: {', '.join(names)}")
        return Flow(registers, stack)
