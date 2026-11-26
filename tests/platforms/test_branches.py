import unittest

from exxlang.compiler import compile_source


def jumps(source):
    return [ins.mnemonic for proc in compile_source(source) for ins in proc.instructions
            if ins.mnemonic in ("jr", "jp", "djnz")]


class BranchLayoutTests(unittest.TestCase):
    def test_forward_limit_with_prefixed_and_single_byte_instructions(self):
        # LD (IX+d),n is four bytes and INC HL is one.
        body = "p[1] = 3; " * 31 + "HL += 1; " * 3
        for extra, expected in (("", "jr"), ("HL += 1", "jp")):
            src = "f(p → IX, h → HL, flag → CF) clobbers(HL) { if (flag) {" + body + extra + "} }"
            self.assertEqual(jumps(src), [expected])

    def test_backward_limit_and_cascading_widening(self):
        # +126 forward, -128 backward. One extra INC forces the backward JP,
        # which in turn pushes the forward displacement from +127 to +128.
        for count, expected in ((124, ["jr", "jr"]), (125, ["jp", "jp"])):
            src = "f(flag → Z, h → HL) clobbers(HL) { while (flag) {" + "HL += 1; " * count + "} }"
            self.assertEqual(jumps(src), expected)

    def test_repeat_boundary(self):
        for count, expected in ((126, ["djnz"]), (127, ["djnz", "jr", "jp"])):
            src = "f(n → B, h → HL) clobbers(B, HL) { repeat(n) {" + "HL += 1; " * count + "} }"
            self.assertEqual(jumps(src), expected)

    def test_condition_codes(self):
        for flag in ("Z", "CF", "S", "PV"):
            for negate in ("", "!"):
                with self.subTest(flag=flag, negate=negate):
                    src = f"f(flag → {flag}) → A {{ if ({negate}flag) return 1; return 2 }}"
                    self.assertEqual(jumps(src), ["jr" if flag in ("Z", "CF") else "jp"])

    def test_module_boundaries_and_opaque_assembly(self):
        caller = "f() { return g() }\n"
        self.assertEqual(jumps(caller + "g() {}"), ["jr"])
        self.assertEqual(jumps("g() {}\n" + caller), ["jr"])
        self.assertEqual(jumps(caller + "extern g()"), ["jp"])
        self.assertEqual(jumps(caller + "asm { nop }\ng() {}"), ["jp"])
        self.assertEqual(jumps("f(flag → Z) { if (flag) { asm { nop } }; return g() }\ng() {}"),
                         ["jp", "jr"])

    def test_short_jump_layout_includes_static_data(self):
        words = "".join(f"data word_{i}: u16 = 0\n" for i in range(63))
        for byte_count, expected in ((1, "jr"), (2, "jp")):
            extra = "".join(f"data byte_{i}: u8 = 0\n" for i in range(byte_count))
            self.assertEqual(jumps("f() { return g() }\n" + words + extra + "g() {}"), [expected])
