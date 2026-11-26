import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import emit


def instructions(source, **options):
    proc, = compile_source(source, **options)
    return [(ins.mnemonic, ins.operands) for ins in proc.instructions]


class MemoryTests(unittest.TestCase):
    def test_dereference_and_index_limits(self):
        code = instructions("f(src → DE, dst → HL, idx → IX) → A clobbers(B) "
                            "{A = *src; *dst = A; B = idx[-128]; idx[126 + 1] = B; return A}")
        self.assertEqual(code, [("ld", ("a", "(de)")), ("ld", ("(hl)", "a")),
                                ("ld", ("b", "(ix - 128)")), ("ld", ("(ix + 127)", "b")), ("ret", ())])
        for statement in ("B = *src", "*src = 1", "A = *A", "A = dst[1]",
                          "A = idx[-129]", "A = idx[128]", "A = idx[B]"):
            with self.subTest(statement=statement), self.assertRaises(ExxError):
                instructions(f"f(src → DE, dst → HL, idx → IX) clobbers(A,B) {{ {statement} }}")
        with self.assertRaisesRegex(ExxError, "D, E unavailable"):
            instructions("f() → A {return *DE}")

    def test_indexed_bit_and_address_of(self):
        abi = [("defs.abi", "extern data table_base\nextern data unused\nfield CTX.ptr: u16")]
        procs = compile_source("f(ctx: CTX → IY) → DE {ctx[-1]$2 = true; "
                               "DE = &table_base; ctx->ptr = DE; return ctx->ptr}", interfaces=abi)
        self.assertEqual(procs[0].externals, {"table_base"})
        text = emit(procs, "z80asm")
        for line in ("EXTERN table_base", "ld de, table_base", "set 2, (iy - 1)",
                     "ld (iy + CTX_ptr), e", "ld (iy + CTX_ptr + 1), d",
                     "ld e, (iy + CTX_ptr)", "ld d, (iy + CTX_ptr + 1)"):
            self.assertIn(line, text)
        self.assertNotIn("unused", text)

    def test_word_immediate_and_width_checks(self):
        prefix = "field CTX.ptr: u16\n"
        code = instructions(prefix + "f(ctx: CTX → IX) {ctx->ptr = 0x1234}")
        self.assertEqual(code[:2], [("ld", ("(ix + CTX.ptr)", "52")),
                                    ("ld", ("(ix + CTX.ptr + 1)", "18"))])
        for statement in ("A = ctx->ptr", "ctx->ptr = A", "IX = ctx->ptr", "ctx->ptr = 65536",
                          "ctx->byte = DE", "HL = &undeclared"):
            with self.subTest(statement=statement), self.assertRaises(ExxError):
                instructions(prefix + f"f(ctx: CTX → IX, v → DE) clobbers(IX, A, HL) {{ {statement} }}")

    def test_interface_conflicts(self):
        for decl in ("field CTX.ptr: u8", "extern data handler", "extern data ix", "extern data exx__reserved"):
            with self.subTest(decl=decl), self.assertRaises(ExxError):
                compile_source(decl, interfaces=[("defs.abi", "extern handler()\nfield CTX.ptr: u16")])


class RepeatTests(unittest.TestCase):
    def test_post_test_loop_preserves_flags(self):
        code = instructions("f(c → CF) → CF clobbers(B) {B = 0; repeat (B) {}; return c}")
        self.assertEqual(code, [("ld", ("b", "0")), ("label", ("exx__f_1",)),
                                ("djnz", ("exx__f_1",)), ("ret", ())])
        with self.assertRaisesRegex(ExxError, "B unavailable"):
            instructions("f() clobbers(B) {repeat (B) {}}")
        with self.assertRaisesRegex(ExxError, "undeclared clobber: B"):
            instructions("f(n → B) {repeat (n) {}}")
        with self.assertRaisesRegex(ExxError, "repeat requires B"):
            instructions("f(n → C) {repeat (n) {}}")

    def test_inner_break_and_dataflow(self):
        code = instructions("f(n → B, ready → Z) → A clobbers(B) {"
                            "repeat (n) { while (ready) { break }; A = 1; if (ready) break }; return A }")
        loop = next(args[0] for op, args in code if op == "djnz")
        self.assertIn(("label", (loop,)), code)
        self.assertIn(("jr", ("z", "exx__f_2")), code)
        with self.assertRaisesRegex(ExxError, "A unavailable"):
            instructions("f(n → B, ready → Z) → A clobbers(B) {repeat (n) {if (ready) break; A = 1}; return A}")
        with self.assertRaisesRegex(ExxError, "enclosing loop"):
            instructions("f() {break}")

    def test_long_repeat_uses_a_local_djnz_and_absolute_back_edge(self):
        body = "HL += 1; " * 130
        code = instructions("f(n → B, p → HL) clobbers(B, HL) {repeat (n) {" + body + "}}")
        self.assertIn(("djnz", ("exx__f_1_again",)), code)
        self.assertIn(("jp", ("exx__f_1",)), code)
