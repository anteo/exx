import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import emit


class DeclarationTests(unittest.TestCase):
    def test_grouped_external_layouts_and_fields_match_flat_declarations(self):
        flat = """
            layout HEADER: 3
            layout ITEM: 2
            field HEADER.item: ITEM
            field ITEM.word: u16
        """
        grouped = """
            layout { HEADER: 3 { item: ITEM }, ITEM: 2 }
            field { ITEM { word: u16 } }
        """
        source = "HL read(header: HEADER) frame(IX) { return header.item.word }"
        for target in ("asm", "sjasmplus", "z80asm"):
            with self.subTest(target=target):
                self.assertEqual(emit(compile_source(flat + source), target),
                                 emit(compile_source(grouped + source), target))

    def test_native_structures_resolve_across_abi_files_in_dependency_order(self):
        module = compile_source("""
            A read(header: HEADER, tag: u8) frame(IY) {
                A = header.item.word_low
                return tag
            }
            data size: u8 = HEADER
            data displacement: u8 = HEADER.item.word_low
        """, interfaces=[
            ("header.abi", "struct HEADER { flag: u8, item: ITEM }"),
            ("item.abi", "struct ITEM { word_low: u8; word_high: u8 }"),
        ])
        plain = emit(module, "asm")
        self.assertIn("ld a, (iy + 5)", plain)
        self.assertIn("ld a, (iy + 7)", plain)
        self.assertIn("size:\n    defb 3", plain)
        self.assertIn("displacement:\n    defb 1", plain)
        sjasmplus = emit(module, "sjasmplus")
        self.assertLess(sjasmplus.index("STRUCT @ITEM"), sjasmplus.index("STRUCT @HEADER"))
        self.assertIn("item @ITEM", sjasmplus)
        z80asm = emit(module, "z80asm")
        self.assertIn("DEFC HEADER_item_word_high = 2", z80asm)

    def test_layout_diagnostics(self):
        for source, diagnostic in (
            ("struct EMPTY {}", "at least one field"),
            ("struct ITEM { byte: u8, byte: u16 }", "duplicate field ITEM.byte"),
            ("struct ITEM { value: MISSING }", "unknown size of MISSING"),
            ("struct ITEM { data: INFO }\nstruct INFO { data: ITEM }", "recursive struct layout"),
            ("struct ITEM { byte: u8 }\nlayout ITEM: 1", "already has layout or field declarations"),
            ("struct ITEM { byte: u8 }\nA read(item: ITEM → IX) { return item->typo }",
             "unknown field ITEM.typo"),
            ("layout PADDED: 127\nstruct ITEM { pad: PADDED, value: u16 }\n"
             "HL read(item: ITEM → IX) { return item->value }", "index displacement"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_source(source)

    def test_const_and_origin_emit_assembler_directives_in_source_order(self):
        module = compile_source("""
            const { BASE = 0x8000, START = BASE + 3 }
            origin START
            data code: u8 = VALUE
            const VALUE = 42
            A get() { return VALUE }
        """)
        for target, definition in (("asm", "BASE EQU 32768"), ("sjasmplus", "BASE EQU 32768"),
                                   ("z80asm", "DEFC BASE = 32768")):
            with self.subTest(target=target):
                output = emit(module, target)
                self.assertLess(output.index(definition), output.index("ORG 32771"))
                self.assertLess(output.index("ORG 32771"), output.index("code:\n    defb 42"))
                self.assertIn("ld a, 42", output)
        with self.assertRaisesRegex(ExxError, "recursive constant"):
            compile_source("const { FIRST = SECOND, SECOND = FIRST }")
