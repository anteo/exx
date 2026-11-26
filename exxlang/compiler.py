"""Register contracts, structured control flow and platform lowering for EXX."""

from collections import deque
from dataclasses import dataclass, field, replace
import operator

from .diagnostics import ExxError
from .flow import Flow
from .parser import parse
from .ir import Instruction, Operand, StaticData, TargetError
from .registry import platforms
from .syntax import Stmt


_BINARY = {"+": operator.add, "-": operator.sub, "^": operator.xor,
           "&": operator.and_, "|": operator.or_, "<<": operator.lshift, ">>": operator.rshift}
_SCALAR_WIDTHS = {"u8": 8, "u16": 16}


@dataclass
class Procedure:
    name: str
    instructions: tuple[Instruction, ...]
    externals: set[str]
    platform: str
    start: int = 0
    end: int = 0


class CompiledModule(list[Procedure]):
    """Lowered procedures and other module items in source order."""

    def __init__(self, procedures, comments, assembly, data):
        super().__init__(procedures)
        self.comments = comments
        self.assembly = assembly
        self.data = data


@dataclass
class Step:
    instruction: Instruction
    line: int
    kills: frozenset = frozenset()
    # A generated push and all matching pops share the push step's index.
    keep_slot: int | None = None
    keep_live: frozenset = frozenset()


@dataclass(frozen=True)
class LocalLabel:
    symbol: str
    scope: tuple[int, ...]
    keep_depth: int


def parts(cpu, names):
    return frozenset().union(*(cpu.resources(name) for name in names))


def elements(expr):
    if expr is None:
        return ()
    return expr.args if expr.kind == "tuple" else (expr,)


def constant_operand(expr, width, resolve):
    if expr.kind == "int":
        return Operand("imm", str(expr.value))
    if expr.kind == "unary" and expr.value in ("+", "-", "~"):
        src = resolve(expr.args[0], width)
        if src.kind != "imm":
            return None
        if expr.value == "+":
            return src
        mask = (1 << width) - 1 if width and expr.value == "~" else None
        try:
            value = int(src.text)
        except ValueError:
            text = f"({expr.value}{src.text})"
            if mask is not None:
                text = f"({text} & {mask})"
        else:
            value = ~value if expr.value == "~" else -value
            text = str(value if mask is None else value & mask)
        return Operand("imm", text, src.width)
    if expr.kind == "binary" and expr.value in _BINARY:
        shift = expr.value in ("<<", ">>")
        left = resolve(expr.args[0], width)
        right = resolve(expr.args[1], 0 if shift else width)
        if left.kind != "imm" or right.kind != "imm":
            return None
        if shift and right.text.lstrip("-").isdecimal() and not 0 <= int(right.text) <= 255:
            raise ExxError(expr.line, "constant shift count must be in 0..255")
        try:
            a, b = int(left.text), int(right.text)
        except ValueError:
            text = f"({left.text} {expr.value} {right.text})"
        else:
            text = str(_BINARY[expr.value](a, b))
        return Operand("imm", text)
    return None


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


@dataclass
class Declarations:
    procedures: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    field_types: dict = field(default_factory=dict)

    def data_address(self, symbol, externals):
        if symbol.kind != "name" or symbol.value not in self.data:
            raise ExxError(symbol.line, "address-of requires a declared data symbol")
        declaration = self.data[symbol.value]
        if declaration.initializer is None:
            externals.add(symbol.value)
        return Operand("imm", symbol.value, 16)


def lower_data(symbol, declarations, cpu):
    externals = set()
    data_width = _SCALAR_WIDTHS[symbol.type_name]

    def resolve(expr, width):
        if expr.kind == "unary" and expr.value == "&":
            if data_width != 16:
                raise ExxError(expr.line, "a data address initializer requires u16")
            return declarations.data_address(expr.args[0], externals)
        if (expr.kind == "name" and expr.value.split(".")[0].isupper()
                and expr.value not in declarations.data and not cpu.register(expr.value)
                and expr.value not in cpu.unsupported_registers):
            return Operand("imm", expr.value)
        value = constant_operand(expr, width, resolve)
        if value is None:
            raise ExxError(expr.line, "a data initializer must be a constant or a data address")
        return value

    operand = resolve(symbol.initializer, data_width)
    value = int(operand.text) if operand.text.lstrip("-").isdecimal() else None
    if value is not None and not -(1 << (data_width - 1)) <= value < (1 << data_width):
        raise ExxError(symbol.line, f"initializer for {symbol.name} does not fit in {data_width} bits")
    return StaticData(symbol.name, data_width, operand.text, frozenset(externals), symbol.start)


def collect_signatures(cpu, program, declarations, *, interface=False):
    if interface and program.assembly:
        raise ExxError(program.assembly[0].line, "an ABI file may only contain declarations")
    found = declarations.procedures
    for symbol in program.data:
        name = symbol.name
        if (name in found or name.lower().startswith("exx__") or cpu.register(name.upper())
                or name.upper() in cpu.unsupported_registers):
            raise ExxError(symbol.line, f"invalid or conflicting data symbol {name}")
        if interface and symbol.initializer is not None:
            raise ExxError(symbol.line, "a shared ABI file may only declare external data")
        previous = declarations.data.get(name)
        if previous is not None:
            if previous.type_name and symbol.type_name and previous.type_name != symbol.type_name:
                raise ExxError(symbol.line, f"conflicting data type for {name}")
            if previous.initializer is not None and symbol.initializer is not None:
                raise ExxError(symbol.line, f"duplicate definition of data {name}")
            if previous.initializer is not None or (previous.type_name and symbol.initializer is None):
                continue
        declarations.data[name] = symbol
    for member in program.fields:
        previous = declarations.field_types.setdefault(member.name, member.type_name)
        if previous != member.type_name:
            raise ExxError(member.line, f"conflicting field type for {member.name}")
    for proc in program.procs:
        if proc.name in declarations.data:
            raise ExxError(proc.line, f"{proc.name} is declared as data")
        if interface and proc.body is not None:
            raise ExxError(proc.line, "a shared ABI file may only contain extern and field declarations")
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
    def __init__(self, proc, declarations, cpu):
        self.cpu = cpu
        self.proc = proc
        self.declarations = declarations
        self.symbols = declarations.procedures
        self.aliases = {p.name: (p.register, p.type_name) for p in proc.params}
        self.layouts = {p.register: p.type_name for p in proc.params if p.type_name}
        self.steps = []
        self.externals = set()
        self.counter = 0
        self.position = proc.start
        self.loop_exits = []
        self.kept_words = []
        self.local_labels = {}
        self.scope = ()
        self.writable = parts(cpu, proc.outputs + proc.clobbers)

    def label(self):
        self.counter += 1
        return f"exx__{self.proc.name}_{self.counter}"

    def emit(self, ins, line, kills=frozenset(), **keep):
        self.steps.append(Step(replace(ins, source_offset=self.position), line, kills, **keep))

    def mark(self, label, line):
        self.emit(Instruction("label", (label,)), line)

    def collect_labels(self, statements, scope=(), keep_depth=0):
        scope += (id(statements),)
        for stmt in statements:
            if stmt.kind == "label":
                if stmt.value in self.local_labels:
                    raise ExxError(stmt.line, f"duplicate label {stmt.value}")
                self.local_labels[stmt.value] = LocalLabel(self.label(), scope, keep_depth)
            if stmt.body:
                nested_depth = keep_depth + (len(stmt.value.args) if stmt.kind == "keep" else 0)
                self.collect_labels(stmt.body, scope, nested_depth)
            if stmt.otherwise:
                self.collect_labels(stmt.otherwise, scope, keep_depth)

    def goto(self, stmt):
        label = self.local_labels.get(stmt.value)
        if label is None:
            raise ExxError(stmt.line, f"unknown label {stmt.value}")
        if self.scope[:len(label.scope)] != label.scope:
            raise ExxError(stmt.line, f"goto {stmt.value} cannot enter a nested or sibling block")
        self.restore_kept(label.keep_depth, stmt.line)
        self.emit(self.cpu.jump(label.symbol), stmt.line)

    def field_operand(self, expr):
        path = []
        base = expr
        while base.kind == "field":
            path.append(base.value)
            base, = base.args
        reg, layout = self.aliases.get(base.value, (None, None))
        if base.kind != "name" or layout is None:
            raise ExxError(expr.line, "field access requires a typed " + " or ".join(self.cpu.layout_registers) + " binding")

        offsets = []
        while len(path) > 1:
            name = f"{layout}.{path.pop()}"
            layout = self.declarations.field_types.get(name)
            if layout is None or layout in _SCALAR_WIDTHS:
                raise ExxError(expr.line, f"{name} requires a nested layout declaration")
            offsets.append(name)
        member, = path
        type_name = self.declarations.field_types.get(f"{layout}.{member}", "u8")
        if type_name not in _SCALAR_WIDTHS:
            raise ExxError(expr.line, f"{layout}.{member} is a nested layout; select a member")
        return self.cpu.field_operand(reg, layout, member, _SCALAR_WIDTHS[type_name], prefix=offsets)

    def operand(self, expr, width=0):
        if expr.kind == "name":
            if expr.value in self.aliases:
                return self.cpu.register(self.aliases[expr.value][0])
            reg = self.cpu.register(expr.value)
            if reg:
                return reg
            if expr.value in self.cpu.unsupported_registers:
                raise ExxError(expr.line, f"unsupported {self.cpu.name.upper()} register {expr.value}")
            declaration = self.declarations.data.get(expr.value)
            if declaration is not None:
                if declaration.type_name is None:
                    raise ExxError(expr.line, f"declare a type for data {expr.value} to access its value")
                address = self.declarations.data_address(expr, self.externals)
                return self.cpu.absolute_operand(address, _SCALAR_WIDTHS[declaration.type_name])
            # Constants and assembler structure offsets remain symbolic.
            if expr.value.split(".")[0].isupper():
                return Operand("imm", expr.value)
            raise ExxError(expr.line, f"unknown name {expr.value}")
        if expr.kind == "assign":
            raise ExxError(expr.line, "parenthesized assignment requires a condition or arithmetic operand")
        if expr.kind == "field":
            return self.field_operand(expr)
        if expr.kind == "unary" and expr.value == "&":
            return self.declarations.data_address(expr.args[0], self.externals)
        if expr.kind == "index":
            base, offset = (self.operand(x) for x in expr.args)
            return self.cpu.indirect_operand(base, offset)
        if expr.kind == "unary" and expr.value == "*":
            return self.cpu.indirect_operand(self.operand(expr.args[0]))
        value = constant_operand(expr, width, self.operand)
        if value is not None:
            return value
        raise ExxError(expr.line, "this expression needs an explicit destination register")

    def value_operand(self, expr, width=0, preserve=frozenset()):
        if expr.kind != "assign":
            return self.operand(expr, width)
        target, rhs = expr.args
        dst = self.operand(target)
        if dst.kind != "reg":
            raise ExxError(expr.line, "a nested assignment requires a register")
        start = len(self.steps)
        self.assign(Stmt("assign", expr.line, rhs, target=target, op="="))
        for step in self.steps[start:]:
            if preserve & (step.instruction.writes | step.instruction.invalidates | step.kills):
                raise ExxError(expr.line, "nested assignment overwrites the left operand or destination address")
        return dst

    def target_code(self, instructions, line):
        for ins in instructions:
            self.emit(ins, line)

    def condition(self, expr, label, truth):
        if expr.kind == "binary" and expr.value in ("==", "!=") and any(arg.kind == "bit" for arg in expr.args):
            bit, other = expr.args if expr.args[0].kind == "bit" else reversed(expr.args)
            value = self.operand(other)
            if value.kind != "imm" or value.text not in ("0", "1"):
                raise ExxError(expr.line, "compare a bit with true, false, 1 or 0")
            matches_set_bit = (value.text == "1") == (expr.value == "==")
            self.condition(bit, label, truth == matches_set_bit)
        elif expr.kind == "bit":
            location, index = (self.operand(x) for x in expr.args)
            self.target_code(self.cpu.bit_branch(location, index, label, truth), expr.line)
        elif expr.kind == "unary" and expr.value == "!":
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
            left = self.value_operand(expr.args[0] if comparison else expr)
            right = self.value_operand(expr.args[1], left.width, self.cpu.operand_reads(left)) if comparison else None
            if comparison and left.kind == "imm" and right.width:
                left = self.operand(expr.args[0], right.width)
            self.target_code(self.cpu.branch(left, expr.value if comparison else None, right,
                                        label, truth, new_label=self.label), expr.line)

    def call(self, expr, targets=None, tail=False):
        callee = self.symbols.get(expr.value)
        if callee is None and expr.value in self.cpu.load_names:
            if tail or targets is None or len(targets) != 1:
                raise ExxError(expr.line, f"assign the result of {expr.value} to one register")
            dst = self.operand(targets[0])
            args = tuple(self.operand(arg) for arg in expr.args)
            self.target_code(self.cpu.load_intrinsic(expr.value, dst, args), expr.line)
            return
        if callee is None and expr.value in self.cpu.update_names:
            if targets is not None or tail:
                raise ExxError(expr.line, f"use {expr.value} as a statement")
            args = tuple(self.operand(arg) for arg in expr.args)
            self.target_code(self.cpu.update_intrinsic(expr.value, args), expr.line)
            return
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
        if tail:
            self.restore_kept(0, expr.line, reads)
        self.emit(self.cpu.call(callee.name, reads, parts(self.cpu, callee.outputs), tail),
                  expr.line, parts(self.cpu, callee.clobbers))

    def assign(self, stmt):
        rhs = stmt.value
        if stmt.target.kind == "bit":
            if stmt.op != "=":
                raise ExxError(stmt.line, "bit assignment requires =")
            location, index = (self.operand(x) for x in stmt.target.args)
            self.target_code(self.cpu.bit_store(location, index, self.operand(rhs)), stmt.line)
            return
        if rhs.kind == "call" and stmt.op == "=":
            self.call(rhs, elements(stmt.target))
            return
        dst = self.operand(stmt.target)
        if dst.kind not in ("reg", "mem", "flag"):
            raise ExxError(stmt.line, "assignment requires a writable location")
        address_reads = self.cpu.operand_reads(dst) if dst.kind == "mem" else frozenset()
        if stmt.op != "=":
            width = 0 if stmt.op in ("<<=", ">>=") else dst.width
            code = self.cpu.binary(dst, stmt.op, self.value_operand(rhs, width, self.cpu.operand_reads(dst)))
        elif rhs.kind == "unary" and rhs.value == "~":
            src = self.value_operand(rhs.args[0], preserve=address_reads)
            code = (self.cpu.move(dst, self.operand(rhs, dst.width)) if src.kind == "imm"
                    else self.cpu.complement(dst, src))
        elif rhs.kind == "binary" and rhs.value in _BINARY:
            left = self.value_operand(rhs.args[0], dst.width, address_reads)
            right_width = 0 if rhs.value in ("<<", ">>") else dst.width
            right = self.value_operand(rhs.args[1], right_width, address_reads | self.cpu.operand_reads(left))
            if left.kind == right.kind == "imm":
                code = self.cpu.move(dst, self.operand(rhs, dst.width))
            else:
                prefix = ()
                if left != dst:
                    if dst.kind != "reg":
                        raise ExxError(stmt.line, "an expression needs an explicit destination register")
                    prefix = self.cpu.move(dst, left)
                    right_reads = self.cpu.operand_reads(right)
                    if any(right_reads & (ins.writes | ins.invalidates) for ins in prefix):
                        raise ExxError(stmt.line, f"loading {dst.text} overwrites the right operand")
                code = prefix + self.cpu.binary(dst, rhs.value, right)
        else:
            code = self.cpu.move(dst, self.value_operand(rhs, preserve=address_reads))
        self.target_code(code, stmt.line)

    def returns(self, stmt):
        if stmt.value and stmt.value.kind == "call":
            self.call(stmt.value, tail=True)
            return
        self.prepare_results(stmt)
        outputs = parts(self.cpu, self.proc.outputs)
        self.restore_kept(0, stmt.line, outputs)
        self.emit(self.cpu.ret(outputs), stmt.line)

    def prepare_results(self, stmt):
        values = elements(stmt.value)
        if len(values) != len(self.proc.outputs):
            raise ExxError(stmt.line, f"expected {len(self.proc.outputs)} return values")
        sources = tuple(self.operand(expr, self.cpu.register(name).width)
                        for expr, name in zip(values, self.proc.outputs))
        code = self.cpu.constant_return(self.proc.outputs, sources, self.writable)
        if code is not None:
            self.target_code(code, stmt.line)
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

    def keep(self, stmt):
        depth = len(self.kept_words)
        for arg in stmt.value.args:
            reg = self.operand(arg)
            ins, = self.cpu.update_intrinsic("push", (reg,))
            slot = len(self.steps)
            self.emit(ins, arg.line, keep_slot=slot)
            self.kept_words.append((slot, reg))
        self.block(stmt.body)
        self.position = stmt.end
        self.restore_kept(depth, stmt.line)
        del self.kept_words[depth:]

    def restore_kept(self, depth, line, live=frozenset()):
        for slot, reg in reversed(self.kept_words[depth:]):
            ins, = self.cpu.update_intrinsic("pop", (reg,))
            self.emit(ins, line, keep_slot=slot, keep_live=live & self.cpu.resources(reg.text))

    def block(self, statements):
        outer = self.aliases
        self.aliases = dict(outer)
        self.scope += (id(statements),)
        for stmt in statements:
            try:
                self.position = stmt.start
                self.statement(stmt)
            except TargetError as error:
                raise ExxError(stmt.line, str(error)) from error
        self.scope = self.scope[:-1]
        self.aliases = outer

    def assembly(self, block):
        def locations(names, *, allow_group=False):
            registers = [self.aliases[name][0] if name in self.aliases else name for name in names]
            validate_group(self.cpu, registers, block.line, allow_group)
            return parts(self.cpu, registers)

        self.position = block.start
        self.emit(Instruction("asm", (block.text,), reads=locations(block.inputs),
                              writes=locations(block.outputs),
                              invalidates=locations(block.clobbers, allow_group=True)), block.line)

    def statement(self, stmt):
        if stmt.kind == "bind":
            for name, reg in stmt.value:
                if name in self.aliases or self.cpu.resources(name) or not self.cpu.register(reg):
                    raise ExxError(stmt.line, f"invalid binding {name} → {reg}")
                self.aliases[name] = (reg, self.layouts.get(reg))
        elif stmt.kind == "assign":
            self.assign(stmt)
        elif stmt.kind == "label":
            self.mark(self.local_labels[stmt.value].symbol, stmt.line)
        elif stmt.kind == "goto":
            self.goto(stmt)
        elif stmt.kind == "asm":
            self.assembly(stmt.value)
        elif stmt.kind == "call":
            self.call(stmt.value)
        elif stmt.kind == "return":
            self.returns(stmt)
        elif stmt.kind == "keep":
            self.keep(stmt)
        elif stmt.kind == "if":
            if (self.loop_exits and self.loop_exits[-1][1] == len(self.kept_words)
                    and not stmt.otherwise and len(stmt.body) == 1
                    and stmt.body[0].kind == "break"):
                self.condition(stmt.value, self.loop_exits[-1][0], True)
                return
            end = self.label()
            alt = self.label() if stmt.otherwise else end
            self.condition(stmt.value, alt, False)
            self.block(stmt.body)
            if stmt.otherwise:
                self.emit(self.cpu.jump(end), stmt.line)
                self.mark(alt, stmt.line)
                self.block(stmt.otherwise)
            self.mark(end, stmt.line)
        elif stmt.kind == "break":
            if not self.loop_exits:
                raise ExxError(stmt.line, "break requires an enclosing loop")
            end, depth = self.loop_exits[-1]
            self.restore_kept(depth, stmt.line)
            self.emit(self.cpu.jump(end), stmt.line)
        elif stmt.kind in ("while", "repeat"):
            start, end = self.label(), self.label()
            self.mark(start, stmt.line)
            if stmt.kind == "while":
                self.condition(stmt.value, end, False)
                back_edge = self.cpu.jump(start)
            else:
                back_edge = self.cpu.repeat_branch(self.operand(stmt.value), start)
            self.loop_exits.append((end, len(self.kept_words)))
            self.block(stmt.body)
            self.loop_exits.pop()
            self.position = stmt.end
            self.emit(back_edge, stmt.line)
            self.mark(end, stmt.line)
        else:
            raise ExxError(stmt.line, f"unsupported statement {stmt.kind!r}")

    def finish(self):
        self.collect_labels(self.proc.body)
        self.block(self.proc.body)
        self.position = self.proc.end
        self.emit(Instruction("end"), self.proc.line)
        labels = {s.instruction.operands[0]: i for i, s in enumerate(self.steps)
                  if s.instruction.mnemonic == "label"}
        # Definite assignment at joins is intersection, also on loop back edges.
        inputs = parts(self.cpu, (p.register for p in self.proc.params))
        layout = self.cpu.storage_layout
        protected = {cell: name for name, cells in layout.items() if name not in self.writable for cell in cells}
        states = {0: Flow.entry(layout, inputs)}
        queue = deque([0])
        while queue:
            index = queue.popleft()
            step = self.steps[index]
            ins = step.instruction
            exit_path = ins.mnemonic == "end" or (not ins.falls_through and ins.branch_target is None)
            after = states[index].advance(step, layout, protected, exit_path)
            if ins.mnemonic == "end":
                if self.proc.outputs:
                    raise ExxError(step.line, f"{self.proc.name} can reach the end without returning its results")
                continue
            successors = [index + 1] if ins.falls_through else []
            if ins.branch_target is not None:
                successors.append(labels[ins.branch_target])
            for dest in successors:
                merged = states[dest].merge(after, self.steps[dest].line) if dest in states else after
                if dest not in states or states[dest] != merged:
                    states[dest] = merged
                    queue.append(dest)
        code = []
        for index, step in enumerate(self.steps):
            # Even unreachable raw assembly may define symbols or assembler directives.
            if index not in states and step.instruction.mnemonic != "asm":
                continue
            ins = step.instruction
            if ins.mnemonic == "end":
                ins = replace(self.cpu.ret(), source_offset=self.proc.end)
            code.append(ins)
        return Procedure(self.proc.name, self.cpu.compact(code), self.externals, self.cpu.name,
                         self.proc.start, self.proc.end)


def compile_source(source: str, *, platform=None, interfaces=()) -> CompiledModule:
    cpu = platforms.create(platform)
    declared = Declarations()
    for path, declarations in interfaces:
        try:
            collect_signatures(cpu, parse(declarations), declared, interface=True)
        except ExxError as error:
            error.source = path
            raise
    comments = []
    program = parse(source, comments=comments)
    collect_signatures(cpu, program, declared)
    data = tuple(lower_data(symbol, declared, cpu) for symbol in program.data if symbol.initializer is not None)
    module = CompiledModule((Lowering(proc, declared, cpu).finish() for proc in program.procs
                             if proc.body is not None), comments, program.assembly, data)
    layout = getattr(cpu, "layout_module", None)
    if layout is not None:
        layout(module)
    return module
