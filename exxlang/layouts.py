"""Sizes, field types, and offsets for EXX and assembler-owned layouts."""

from .diagnostics import ExxError, declaration_conflict
from .ir import StructDefinition, StructMember


SCALAR_WIDTHS = {"u8": 8, "u16": 16}


class LayoutTable:
    def __init__(self):
        self.sizes = {}
        self.field_types = {}
        self.structs = {}
        self.offsets = {}
        self.definitions = {}
        self._external_layouts = {}
        self._layout_sites = {}
        self._field_sites = {}

    def collect(self, program, source):
        try:
            for layout in program.layouts:
                if layout.name in SCALAR_WIDTHS or layout.size == 0:
                    raise ExxError(layout.line, "a layout requires a non-scalar name and a positive byte size")
                self._declare_external(layout.name, layout.line, source)
                previous = self.sizes.setdefault(layout.name, layout.size)
                if previous != layout.size:
                    raise declaration_conflict(layout.line, f"conflicting layout size for {layout.name}",
                                               *self._layout_sites[layout.name])
                self._layout_sites.setdefault(layout.name, (layout.line, source))
            for member in program.fields:
                self._declare_external(member.name.rpartition(".")[0], member.line, source)
                previous = self.field_types.setdefault(member.name, member.type_name)
                if previous != member.type_name:
                    raise declaration_conflict(member.line, f"conflicting field type for {member.name}",
                                               *self._field_sites[member.name])
                self._field_sites.setdefault(member.name, (member.line, source))
            for struct in program.structs:
                if struct.name in SCALAR_WIDTHS or not struct.members:
                    raise ExxError(struct.line, "a struct requires a non-scalar name and at least one field")
                if struct.name in self._external_layouts:
                    raise declaration_conflict(struct.line, f"{struct.name} already has layout or field declarations",
                                               *self._external_layouts[struct.name])
                if struct.name in self.structs:
                    previous, path = self.structs[struct.name]
                    raise declaration_conflict(struct.line, f"duplicate definition of struct {struct.name}",
                                               previous.line, path)
                self.structs[struct.name] = (struct, source)
        except ExxError as error:
            error.source = source
            raise

    def _declare_external(self, name, line, source):
        if name in self.structs:
            previous, path = self.structs[name]
            raise declaration_conflict(line, f"{name} is already defined as a struct", previous.line, path)
        self._external_layouts.setdefault(name, (line, source))

    def size(self, name):
        width = SCALAR_WIDTHS.get(name)
        return width // 8 if width else self.sizes.get(name)

    def resolve(self):
        for name in self.structs:
            self._resolve_struct(name, ())

    def _resolve_struct(self, name, parents):
        if name in self.sizes:
            return self.sizes[name]
        struct, source = self.structs[name]
        chain = (*parents, name)
        if name in parents:
            error = ExxError(struct.line, "recursive struct layout: " + " → ".join(chain))
            error.source = source
            raise error
        size = 0
        members = []
        for member in struct.members:
            field = f"{name}.{member.name}"
            member_size = self.size(member.type_name)
            if field in self.field_types:
                reason = f"duplicate field {field}"
            elif member_size is None and member.type_name not in self.structs:
                reason = f"unknown size of {member.type_name} in {field}"
            else:
                reason = None
            if reason is not None:
                error = ExxError(member.line, reason)
                error.source = source
                raise error
            if member_size is None:
                member_size = self._resolve_struct(member.type_name, chain)
            self.field_types[field] = member.type_name
            self.offsets[field] = size
            members.append(StructMember(member.name, member.type_name, member_size, size))
            size += member_size
        self.sizes[name] = size
        self.definitions[name] = StructDefinition(name, size, tuple(members))
        return size

    def member_path(self, layout, path, line):
        offsets = []
        for index, member in enumerate(path):
            field = f"{layout}.{member}"
            type_name = self.field_types.get(field)
            if type_name is None and layout in self.structs:
                raise ExxError(line, f"unknown field {field}")
            offsets.append(self.offsets.get(field, field))
            if index == len(path) - 1:
                return type_name or "u8", offsets
            if type_name is None or type_name in SCALAR_WIDTHS:
                raise ExxError(line, f"{field} requires a nested layout declaration")
            layout = type_name

    def native_offset(self, name, line):
        parts = name.split(".")
        for split in range(len(parts) - 1, 0, -1):
            layout = ".".join(parts[:split])
            if layout in self.structs:
                _, offsets = self.member_path(layout, parts[split:], line)
                return offset_expression(offsets)


def offset_expression(offsets):
    numeric = sum(term for term in offsets if isinstance(term, int))
    symbols = [term for term in offsets if isinstance(term, str)]
    if not symbols:
        return str(numeric)
    return " + ".join([str(numeric), *symbols] if numeric else symbols)
