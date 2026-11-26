import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import emit


class StackArgumentTests(unittest.TestCase):
    def test_compact_and_explicit_stack_abi_match(self):
        definitions = """
            layout SURFACE: 3
            field SURFACE.page0: u8
            extern (A, C, HL) read(first: u8 → stack[2], p → B, image: SURFACE → stack[3],
                                  value: u16 → stack[6]) clobbers(CF, HF, N)
            (A, C, HL) read(mode: u8, x → B, surface: SURFACE, length: u16)
                frame(IX) clobbers(CF, HF, N) {
                A = mode
                C = surface.page0
                HL = length
            }
        """
        assembly = emit(compile_source(definitions), "asm")
        for instruction in ("ld a, (ix + 4)", "ld c, (ix + 5 + SURFACE.page0)",
                            "ld l, (ix + 8)", "ld h, (ix + 8 + 1)"):
            self.assertIn(instruction, assembly)
        with self.assertRaisesRegex(ExxError, "incompatible ABI"):
            compile_source(definitions.replace("stack[6]", "stack[7]"))

    def test_frame_preserves_input_carry_and_unwinds_keep_on_return_and_goto(self):
        assembly = emit(compile_source("""
            A read(value: u8, flag → CF) frame(IY) clobbers(CF, HF, N) {
                keep(DE) {
                    if (flag) return value
                    goto done
                }
            done:
                A = 0
            }
        """), "asm")
        self.assertIn("push iy\n    push af\n    ld iy, 2\n    add iy, sp\n    pop af", assembly)
        self.assertIn("jr nc,", assembly)
        self.assertIn("ld a, (iy + 4)\n    pop de\n    pop iy\n    ret", assembly)
        self.assertIn("pop de\n    ld a, 0\n    pop iy\n    ret", assembly)

    def test_ordinary_call_can_receive_frame_and_tail_exit_restores_it(self):
        assembly = emit(compile_source("""
            extern helper(frame_pointer → IX)
            extern A finish(value → A)
            A read(value: u8) frame(IX) clobbers(CF, HF, N) {
                helper(IX)
                A = value
                return finish(A)
            }
        """), "asm")
        self.assertIn("call helper\n    ld a, (ix + 4)\n    pop ix\n    jp finish", assembly)

    def test_frameless_procedure_can_leave_stack_parameters_unused(self):
        assembly = emit(compile_source("A read(value: u8) { return 0 }"), "asm")
        self.assertIn("read:\n    ld a, 0\n    ret", assembly)

    def test_stack_and_frame_diagnostics(self):
        for source, diagnostic in (
            ("f(x: u8) { A = x }", "requires a frame"),
            ("f(x: u8) frame(HL) {}", "frame requires IX or IY"),
            ("f(x: u8, base → IX) frame(IX) {}", "must be preserved"),
            ("extern f(x: u8) frame(IX)", "belongs on the procedure definition"),
            ("f(x: MISSING) {}", "unknown size"),
            ("layout RECORD: 0", "positive byte size"),
            ("f(x: u8 → stack[1]) {}", "overlaps the return address"),
            ("f(x: u16, y: u8 → stack[3]) {}", "overlapping stack parameters"),
            ("f(x: u16 → stack[125]) frame(IY) {}", "displacement limit"),
            ("f(x: u8) frame(IX) { x = 1 }", "read-only"),
            ("f(x: u8) frame(IX) { x$0 = 1 }", "read-only"),
            ("f(x: u8) frame(IX) { sra(x) }", "read-only"),
            ("f(x: u8) frame(IX) { IX = 0 }", "cannot modify active frame register IX"),
            ("f(x: u8) frame(IY) { push(HL); pop(IY) }", "cannot modify active frame register IY"),
            ("extern g() clobbers(IX)\nf(x: u8) frame(IX) { g() }", "cannot modify active frame register IX"),
            ("extern g(frame_pointer → IX)\nf(x: u8) frame(IX) { return g(IX) }",
             "restoration would overwrite live IX"),
            ("extern g(x: u8)\nf() { g(1) }", "require an asm block"),
            ("CF f(x: u8) frame(IX) clobbers(HF, N) {}", "CF unavailable"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_source(source)
