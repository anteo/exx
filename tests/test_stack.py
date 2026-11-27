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
            ("extern g(x: u8)\nf() { g(1) }", "stack argument needs an explicit 8-bit register"),
            ("CF f(x: u8) frame(IX) clobbers(HF, N) {}", "CF unavailable"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_source(source)


class StackCallTests(unittest.TestCase):
    def test_word_byte_and_explicit_register_input(self):
        assembly = emit(compile_source("""
            extern (CF, A) probe(word: u16, tag: u8, page → D) clobbers(HF, N)
            (CF, A) relay(word → HL, tag → B, page → E) clobbers(D, HF, N) {
                return probe(word, tag, (D = page))
            }
        """), "asm")
        self.assertIn("push bc\n    inc sp\n    push hl\n    ld d, e\n    call probe\n"
                      "    inc sp\n    inc sp\n    inc sp\n    ret", assembly)

    def test_stack_call_restores_keep_after_cleaning_arguments(self):
        assembly = emit(compile_source("""
            extern (CF, A) probe(value: u8) clobbers(B, HF, N)
            (CF, A) relay(value → A) clobbers(HF, N) {
                keep(BC) { return probe(value) }
            }
        """), "asm")
        self.assertIn("push bc\n    push af\n    inc sp\n    call probe\n    inc sp\n    pop bc\n    ret", assembly)

    def test_logical_arguments_can_share_a_push_across_structure_boundary(self):
        assembly = emit(compile_source("""
            struct SURFACE { mode: u8, page0: u8, page1: u8 }
            extern data draw
            extern put(surface: SURFACE, x: u8, y: u8, character: u8)
            paint(x → B, page1 → C, character → D, y → E) clobbers(HL) {
                head → HL
                head = *(&draw)
                put(SURFACE {
                    page1: page1
                    mode: head.lo
                    page0: head.hi
                }, x, y, character)
            }
        """), "asm")
        self.assertIn("ld hl, (draw)\n    push de\n    push bc\n    push hl\n    call put\n"
                      + "    inc sp\n" * 6 + "    ret", assembly)

    def test_explicit_loads_are_evaluated_in_stack_order(self):
        assembly = emit(compile_source("""
            struct HEADER { mode: u8, pair: PAIR }
            struct PAIR { lo: u8, hi: u8 }
            extern sink(header: HEADER, character: u8)
            send(character → A) clobbers(A, HL) {
                sink(HEADER {
                    pair: PAIR { lo: (L = 1), hi: (H = 2) }
                    mode: (A = 3)
                }, character)
            }
        """), "asm")
        self.assertIn("push af\n    inc sp\n    ld h, 2\n    ld l, 1\n    push hl\n"
                      "    ld a, 3\n    push af\n    inc sp\n    call sink", assembly)

    def test_pushes_old_byte_before_its_register_is_reused(self):
        assembly = emit(compile_source("""
            extern sink(left: u8, right: u8)
            send() clobbers(A) { sink((A = 1), (A = 2)) }
        """), "asm")
        self.assertIn("ld a, 2\n    push af\n    inc sp\n    ld a, 1\n    push af\n    inc sp\n    call sink", assembly)

    def test_explicit_slots_reserve_padding_by_offset(self):
        assembly = emit(compile_source("""
            extern pack(tag: u8 → stack[5], value: u16 → stack[2])
            send(tag → H, value → IX) { pack(tag, value) }
        """), "asm")
        self.assertIn("push hl\n    inc sp\n    dec sp\n    push ix\n    call pack\n"
                      + "    inc sp\n" * 4 + "    ret", assembly)

    def test_stack_call_diagnostics(self):
        for source, diagnostic in (
            ("extern g(x: u8)\nf(low → L) { g(low) }", "unpaired stack byte needs A, B, D or H"),
            ("extern g(x: u16)\nf(byte → B) { g(byte) }", "explicit 16-bit register"),
            ("extern g(x: u8)\nf() { g(A) }", "A unavailable"),
            ("extern g(x: u8, other → A)\nf(other → A) clobbers(A) { g((A = 1), other) }",
             "argument preparation overwrites a register argument: A"),
            ("struct ITEM { ch: u8 }\nextern g(x: ITEM)\nf() { g(ITEM {}) }", "missing field ITEM.ch"),
            ("struct ITEM { ch: u8 }\nextern g(x: ITEM)\nf() { g(ITEM { color: A }) }", "unknown field ITEM.color"),
            ("struct ITEM { ch: u8 }\nextern g(x: ITEM)\nf() { g(ITEM { ch: A, ch: A }) }", "duplicate field ITEM.ch"),
            ("layout ITEM: 1\nextern g(x: ITEM)\nf() { g(ITEM { ch: A }) }", "needs a native struct"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_source(source)
