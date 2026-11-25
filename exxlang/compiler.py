"""Register contracts, structured control flow and platform lowering for EXX."""

from collections import deque
from dataclasses import dataclass

from .diagnostics import ExxError
from .parser import parse
from .ir import Instruction, Operand, TargetError
from .registry import platforms
from .syntax import Stmt


@dataclass
class Procedure:
    name: str
    instructions: tuple[Instruction, ...]
    externals: set[str]
    platform: str


@dataclass
class Step:
    instruction: Instruction
    line: int
    kills: frozenset = frozenset()


def parts(cpu, names):
    return frozenset().union(*(cpu.resources(name) for name in names))


def elements(expr):
    if expr is None:
        return ()
    return expr.args if expr.kind == "tuple" else (expr,)


def validate_group(cpu, names, line, allow_group=False):
    used = set()
    for name in names:
        locations = cpu.resources(name)
        if name in cpu.reserved_abi:
            raise ExxError(line, cpu.reserved_abi[name])
        if not locations or (not allow_group and cpu.register(name) is None):
            raise ExxError(line, f"unknown ABI register {name}")
        if used & locations:
            raise ExxError(line, f"overlapping ABI locations at {name}")
        used.update(locations)


def abi_key(cpu, proc):
    inputs = tuple((p.register, p.type_name) for p in proc.params)
    return inputs, proc.outputs, parts(cpu, proc.clobbers) - parts(cpu, proc.outputs)


def collect_signatures(cpu, program, found, *, interface=False):
    for proc in program.procs:
        if interface and proc.body is not None:
            raise ExxError(proc.line, "a shared ABI file may only contain extern declarations")
        if proc.name.lower().startswith("exx__"):
            raise ExxError(proc.line, "the exx__ prefix is reserved for generated labels")
        validate_group(cpu, (p.register for p in proc.params), proc.line)
        validate_group(cpu, proc.outputs, proc.line)
        validate_group(cpu, proc.clobbers, proc.line, allow_group=True)
        names = set()
        for p in proc.params:
            if p.name in names or (cpu.resources(p.name) and p.name != p.register):
                raise ExxError(p.line, f"invalid or duplicate parameter name {p.name}")
            if p.type_name and p.register not in cpu.layout_registers:
                raise ExxError(p.line, "an EXX structure pointer requires " + " or ".join(cpu.layout_registers))
            names.add(p.name)
        previous = found.get(proc.name)
        if previous is not None:
            if abi_key(cpu, previous) != abi_key(cpu, proc):
                raise ExxError(proc.line, f"incompatible ABI for {proc.name}")
            if previous.body is not None and proc.body is not None:
                raise ExxError(proc.line, f"duplicate definition of {proc.name}")
        if previous is None or proc.body is not None:
            found[proc.name] = proc


class Lowering:
    def __init__(self, proc, symbols, cpu):
        self.cpu = cpu
        self.proc = proc
        self.symbols = symbols
        self.aliases = {p.name: (p.register, p.type_name) for p in proc.params}
        self.layouts = {p.register: p.type_name for p in proc.params if p.type_name}
        self.steps = []
        self.externals = set()
        self.counter = 0
        self.writable = parts(cpu, proc.outputs + proc.clobbers)

    def label(self):
        self.counter += 1
        return f"exx__{self.proc.name}_{self.counter}"

    def emit(self, ins, line, kills=frozenset()):
        self.steps.append(Step(ins, line, kills))

    def mark(self, label, line):
        self.emit(Instruction("label", (label,)), line)

    def operand(self, expr):
        if expr.kind == "name":
            if expr.value in self.aliases:
                return self.cpu.register(self.aliases[expr.value][0])
            reg = self.cpu.register(expr.value)
            if reg:
                return reg
            if expr.value in self.cpu.unsupported_registers:
                raise ExxError(expr.line, f"unsupported {self.cpu.name.upper()} register {expr.value}")
            # Constants and assembler structure offsets remain symbolic.
            if expr.value.split(".")[0].isupper():
                return Operand("imm", expr.value)
            raise ExxError(expr.line, f"unknown name {expr.value}")
        if expr.kind == "assign":
            raise ExxError(expr.line, "parenthesized assignment is only supported in conditions")
        if expr.kind == "int":
            return Operand("imm", str(expr.value))
        if expr.kind == "field":
            base = expr.args[0]
            if base.kind == "name" and base.value in self.aliases:
                reg, layout = self.aliases[base.value]
                if layout:
                    return self.cpu.field_operand(reg, layout, expr.value)
            raise ExxError(expr.line, "field access requires a typed " + " or ".join(self.cpu.layout_registers) + " binding")
        if expr.kind == "unary" and expr.value in ("+", "-"):
            src = self.operand(expr.args[0])
            if src.kind == "imm":
                if expr.value == "+":
                    return src
                try:
                    text = str(-int(src.text))
                except ValueError:
                    text = f"(-{src.text})"
                return Operand("imm", text)
        if expr.kind == "binary" and expr.value in ("+", "-", "^"):
            left, right = (self.operand(x) for x in expr.args)
            if left.kind == right.kind == "imm":
                try:
                    a, b = int(left.text), int(right.text)
                except ValueError:
                    text = f"({left.text} {expr.value} {right.text})"
                else:
                    text = str({"+": a + b, "-": a - b, "^": a ^ b}[expr.value])
                return Operand("imm", text)
        raise ExxError(expr.line, "this expression needs an explicit destination register")

    def condition_operand(self, expr):
        if expr.kind != "assign":
            return self.operand(expr)
        target, rhs = expr.args
        dst = self.operand(target)
        if dst.kind != "reg":
            raise ExxError(expr.line, "a condition assignment requires a register")
        self.assign(Stmt("assign", expr.line, rhs, target=target, op="="))
        return dst

    def target_code(self, instructions, line):
        for ins in instructions:
            self.emit(ins, line)

    def condition(self, expr, label, truth):
        if expr.kind == "unary" and expr.value == "!":
            self.condition(expr.args[0], label, not truth)
        elif expr.kind == "binary" and expr.value in ("&&", "||"):
            left, right = expr.args
            if (expr.value == "||") == truth:
                self.condition(left, label, truth)
                self.condition(right, label, truth)
            else:
                skip = self.label()
                self.condition(left, skip, not truth)
                self.condition(right, label, truth)
                self.mark(skip, expr.line)
        else:
            comparison = expr.kind == "binary" and expr.value in ("==", "!=", "<", ">", "<=", ">=")
            left = self.condition_operand(expr.args[0] if comparison else expr)
            start = len(self.steps)
            right = self.condition_operand(expr.args[1]) if comparison else None
            for step in self.steps[start:]:
                if self.cpu.operand_reads(left) & (step.instruction.writes | step.kills):
                    raise ExxError(expr.line, "right operand overwrites the left operand; use an explicit move")
            self.target_code(self.cpu.branch(left, expr.value if comparison else None, right,
                                        label, truth, new_label=self.label), expr.line)

    def call(self, expr, targets=None, tail=False):
        callee = self.symbols.get(expr.value)
        if callee is None:
            raise ExxError(expr.line, f"undeclared procedure {expr.value}")
        if len(expr.args) != len(callee.params):
            raise ExxError(expr.line, f"{callee.name} expects {len(callee.params)} arguments")
        for arg, param in zip(expr.args, callee.params):
            loc = self.operand(arg)
            if loc != self.cpu.register(param.register):
                raise ExxError(arg.line, f"{callee.name}: {param.name} expects {param.register}, got {loc.text}")
            if param.type_name and self.layouts.get(loc.text) != param.type_name:
                layout = self.layouts.get(loc.text, "untyped register")
                raise ExxError(arg.line, f"{param.name} requires layout {param.type_name}, got {layout}")
        if targets is not None:
            actual = tuple(self.operand(t) for t in targets)
            if actual != tuple(self.cpu.register(o) for o in callee.outputs):
                raise ExxError(expr.line, f"{callee.name} returns ({', '.join(callee.outputs)}); capture the declared locations")
        if tail and self.proc.outputs != callee.outputs:
            raise ExxError(expr.line, f"tail call to {callee.name} has incompatible results")
        if callee.body is None:
            self.externals.add(callee.name)
        reads = parts(self.cpu, (p.register for p in callee.params))
        self.emit(self.cpu.call(callee.name, reads, parts(self.cpu, callee.outputs), tail),
                  expr.line, parts(self.cpu, callee.clobbers))

    def assign(self, stmt):
        rhs = stmt.value
        if rhs.kind == "call" and stmt.op == "=":
            self.call(rhs, elements(stmt.target))
            return
        dst = self.operand(stmt.target)
        if dst.kind not in ("reg", "mem", "flag"):
            raise ExxError(stmt.line, "assignment requires a writable location")
        if stmt.op != "=":
            code = self.cpu.binary(dst, stmt.op, self.operand(rhs))
        elif rhs.kind == "binary" and rhs.value in ("+", "-", "^"):
            left, right = (self.operand(x) for x in rhs.args)
            if left.kind == right.kind == "imm":
                code = self.cpu.move(dst, self.operand(rhs))
            elif left == dst:
                code = self.cpu.binary(dst, rhs.value, right)
            else:
                raise ExxError(stmt.line, f"assign the left operand to {dst.text} explicitly first")
        else:
            code = self.cpu.move(dst, self.operand(rhs))
        self.target_code(code, stmt.line)

    def returns(self, stmt):
        if stmt.value and stmt.value.kind == "call":
            self.call(stmt.value, tail=True)
            return
        values = elements(stmt.value)
        if len(values) != len(self.proc.outputs):
            raise ExxError(stmt.line, f"expected {len(self.proc.outputs)} return values")
        sources = tuple(self.operand(expr) for expr in values)
        code = self.cpu.constant_return(self.proc.outputs, sources, self.writable)
        if code is not None:
            self.target_code(code, stmt.line)
            self.emit(self.cpu.ret(parts(self.cpu, self.proc.outputs)), stmt.line)
            return
        # Evaluate tuple sources in their original locations. Keep later
        # operands and every previously established result live during moves.
        protected = set()
        pending = []
        for name, src in zip(self.proc.outputs, sources):
            code = self.cpu.move(self.cpu.register(name), src)
            if not code:
                protected.update(self.cpu.resources(name))
            else:
                reads, writes = set(), set()
                for ins in code:
                    reads.update(ins.reads - writes)
                    writes.update(ins.writes)
                pending.append((name, code, reads, writes))
        while pending:
            for i, (name, code, reads, writes) in enumerate(pending):
                live = protected.union(*(p[2] for j, p in enumerate(pending) if j != i))
                if not writes & live:
                    self.target_code(code, stmt.line)
                    protected.update(self.cpu.resources(name))
                    pending.pop(i)
                    break
            else:
                raise ExxError(stmt.line, "return values overlap; prepare result registers explicitly")
        self.emit(self.cpu.ret(parts(self.cpu, self.proc.outputs)), stmt.line)

    def block(self, statements):
        outer = self.aliases
        self.aliases = dict(outer)
        for stmt in statements:
            try:
                self.statement(stmt)
            except TargetError as error:
                raise ExxError(stmt.line, str(error)) from error
        self.aliases = outer

    def statement(self, stmt):
        if stmt.kind == "bind":
            for name, reg in stmt.value:
                if name in self.aliases or self.cpu.resources(name) or not self.cpu.register(reg):
                    raise ExxError(stmt.line, f"invalid binding {name} → {reg}")
                self.aliases[name] = (reg, self.layouts.get(reg))
        elif stmt.kind == "assign":
            self.assign(stmt)
        elif stmt.kind == "call":
            self.call(stmt.value)
        elif stmt.kind == "return":
            self.returns(stmt)
        elif stmt.kind == "if":
            end = self.label()
            alt = self.label() if stmt.otherwise else end
            self.condition(stmt.value, alt, False)
            self.block(stmt.body)
            if stmt.otherwise:
                self.emit(self.cpu.jump(end), stmt.line)
                self.mark(alt, stmt.line)
                self.block(stmt.otherwise)
            self.mark(end, stmt.line)
        elif stmt.kind == "while":
            start, end = self.label(), self.label()
            self.mark(start, stmt.line)
            self.condition(stmt.value, end, False)
            self.block(stmt.body)
            self.emit(self.cpu.jump(start), stmt.line)
            self.mark(end, stmt.line)
        else:
            raise ExxError(stmt.line, f"unsupported statement {stmt.kind!r}")

    def finish(self):
        self.block(self.proc.body)
        self.emit(Instruction("end"), self.proc.line)
        labels = {s.instruction.operands[0]: i for i, s in enumerate(self.steps)
                  if s.instruction.mnemonic == "label"}
        # Definite assignment at joins is intersection, also on loop back edges.
        states = {0: parts(self.cpu, (p.register for p in self.proc.params))}
        queue = deque([0])
        while queue:
            index = queue.popleft()
            step = self.steps[index]
            ins = step.instruction
            available = states[index]
            if ins.reads - available:
                missing = ", ".join(sorted(ins.reads - available))
                raise ExxError(step.line, f"{missing} unavailable (uninitialized or clobbered)")
            changed = (ins.writes | step.kills) - self.writable
            if changed:
                raise ExxError(step.line, f"undeclared clobber: {', '.join(sorted(changed))}")
            after = (available - step.kills) | ins.writes
            if ins.mnemonic == "end":
                if self.proc.outputs:
                    raise ExxError(step.line, f"{self.proc.name} can reach the end without returning its results")
                continue
            successors = [index + 1] if ins.falls_through else []
            if ins.branch_target is not None:
                successors.append(labels[ins.branch_target])
            for dest in successors:
                merged = states[dest] & after if dest in states else after
                if dest not in states or states[dest] != merged:
                    states[dest] = merged
                    queue.append(dest)
        code = []
        for index, step in enumerate(self.steps):
            if index not in states:
                continue
            ins = step.instruction
            if ins.mnemonic == "end":
                ins = self.cpu.ret()
            code.append(ins)
        return Procedure(self.proc.name, self.cpu.compact(code), self.externals, self.cpu.name)


def compile_source(source: str, *, platform=None, interfaces=()) -> list[Procedure]:
    cpu = platforms.create(platform)
    declared = {}
    for path, declarations in interfaces:
        try:
            collect_signatures(cpu, parse(declarations), declared, interface=True)
        except ExxError as error:
            error.source = path
            raise
    program = parse(source)
    collect_signatures(cpu, program, declared)
    return [Lowering(proc, declared, cpu).finish() for proc in program.procs if proc.body is not None]
