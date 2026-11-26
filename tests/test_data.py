import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import emit


class DataTests(unittest.TestCase):
    def test_data_definitions_share_source_order_with_procedures(self):
        module = compile_source("""// Initial screen pointer.
data cursor: u16 = 0x4000
read_cursor() → HL { return cursor }
data status: u8 = 1 << 2
write_status(value → A) { status = value }
""")
        for target in ("asm", "z80asm"):
            with self.subTest(target=target):
                text = emit(module, target)
                sequence = ("; Initial screen pointer.", "cursor:", "defw 16384",
                            "read_cursor:", "ld hl, (cursor)", "status:", "defb 4",
                            "write_status:", "ld (status), a")
                start = 0
                for part in sequence:
                    start = text.index(part, start) + len(part)
        text = emit(module, "z80asm")
        self.assertIn("    PUBLIC cursor\n", text)
        self.assertIn("    PUBLIC status\n", text)
        self.assertNotIn("EXTERN", text)

    def test_typed_external_data_can_be_read_or_used_in_an_initializer(self):
        abi = [("data.abi", "extern data counter: u16")]
        module = compile_source("""
data counter_ptr: u16 = &counter
get() → DE { return counter }
address() → HL { return &counter }
""", interfaces=abi)
        output = emit(module, "z80asm")
        self.assertEqual(output.count("    EXTERN counter\n"), 1)
        self.assertIn("    defw counter\n", output)
        self.assertIn("    ld de, (counter)\n", output)
        self.assertIn("    ld hl, counter\n", output)
        definition = compile_source("data counter: u16 = 2", interfaces=abi)
        self.assertIn("    PUBLIC counter\n", emit(definition, "z80asm"))
        self.assertFalse(definition.data[0].externals)

    def test_data_checks_types_and_widths(self):
        for source, diagnostic in (
            ("data count: u8 = 256", "does not fit"),
            ("data count: u16 = HL", "initializer must be"),
            ("extern data other\ndata count: u8 = &other + 1", "requires u16"),
            ("data count: u16 = 1\ndata count: u16 = 2", "duplicate definition"),
            ("extern data count: u8\ndata count: u16 = 1", "conflicting data type"),
            ("extern data count\nf() → A { return count }", "declare a type"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_source(source)
        with self.assertRaisesRegex(ExxError, "may only declare external data"):
            compile_source("", interfaces=[("data.abi", "data count: u8 = 0")])
