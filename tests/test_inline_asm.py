import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import emit


class InlineAssemblyTests(unittest.TestCase):
    def test_contract_resolves_alias_halves_and_checks_overlap(self):
        source = "BC f(word → BC) { asm(word.hi) → word.lo { ld c,b } }"
        proc, = compile_source(source)
        block = proc.instructions[0]
        self.assertEqual((block.reads, block.writes), ({"B"}, {"C"}))
        with self.assertRaisesRegex(ExxError, "overlapping"):
            compile_source("f(word → BC) { asm(word, word.lo) { nop } }")

    def test_file_blocks_keep_their_order_and_native_syntax(self):
        native = '\tdefb "}","{",\'}\' ; unmatched }\n\t; // /* #ifdef\n\tMAC {arg}\n'
        source = ("asm {\n    IFDEF DEBUG\n" + native + "    ENDIF\n}\n"
                  "first() {}\nasm {\nmid.label: defb 3\n}\n"
                  "second() {}\nasm {\n    #tail\n}")
        for target in ("asm", "z80asm"):
            output = emit(compile_source(source), target)
            items = ("    IFDEF DEBUG\n" + native + "    ENDIF",
                     "first:", "mid.label: defb 3", "second:", "    #tail")
            offset = 0
            for item in items:
                offset = output.index(item, offset) + len(item)
        self.assertIn("only.label:", emit(compile_source("asm {only.label:}"), "z80asm"))

    def test_contract_uses_aliases_and_checks_reads_writes_and_flags(self):
        source = ("(A, CF) f(value → A) clobbers(F) {\n"
                  "asm(value) -> (value, CF) clobbers(F) {    rlca }\nreturn (value, CF) }")
        self.assertIn("    rlca \n    ret", emit(compile_source(source), "asm"))
        for source, message in (
            ("f() { asm(A) { nop } }", "A unavailable"),
            ("f() { asm() → B { ld b,0 } }", "undeclared clobber"),
            ("B f(b → B) { asm clobbers(B) { nop }; return b }", "B unavailable"),
            ("f(b → BC) { asm(b, C) { nop } }", "overlapping"),
            ("f() { asm clobbers(SP) { nop } }", "reserved"),
            ("asm(A) { nop }", "file-scope"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, message):
                compile_source(source)

    def test_stack_contract_and_opaque_body(self):
        source = """f() {
    keep(AF) {
        asm clobbers(AF) {
            ex af,af'
            ex af,af' ; }
        }
    }
}"""
        output = emit(compile_source(source), "asm")
        self.assertIn("    push af\n            ex af,af'\n            ex af,af' ; }\n    pop af", output)

    def test_labels_and_directives_after_return_are_emitted(self):
        source = "f() { return; asm {\nend_marker:\n    ASSERT end_marker-f == 1\n} }"
        self.assertIn("    ret\nend_marker:\n    ASSERT", emit(compile_source(source), "asm"))

    def test_repeat_uses_long_edge_only_when_crossing_raw_assembly(self):
        f = "f(n → B) clobbers(B) { "
        loop = "repeat(n) { asm {    defs 256 } }"
        self.assertIn("djnz exx__f_1_again", emit(compile_source(f + loop + "}"), "asm"))
        self.assertIn("djnz exx__f_1\n", emit(compile_source(f + "asm { nop }; repeat(n) {} }"), "asm"))

    def test_unterminated_body_and_abi_files(self):
        with self.assertRaisesRegex(ExxError, "unterminated asm block") as error:
            compile_source("\nasm {\n    defb '}' ; }\n")
        self.assertEqual(error.exception.line, 2)
        with self.assertRaisesRegex(ExxError, "ABI file"):
            compile_source("", interfaces=[("shared.abi", "asm { nop }")])
