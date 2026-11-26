import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.platforms.z80 import FLAGS


def compile_body(signature, body):
    proc, = compile_source(f"{signature} {{ {body} }}", platform="z80")
    return proc.instructions


class BitOperationTests(unittest.TestCase):
    def test_bit_modification_preserves_flags_and_uses_old_byte(self):
        code = compile_body("(B, CF) example(x → B, c → CF)", "x$7 = true; x$0 = false; return (x, c)")
        for ins, mnemonic in zip(code, ("set", "res")):
            self.assertEqual((ins.mnemonic, ins.reads, ins.writes), (mnemonic, {"B"}, {"B"}))
        with self.assertRaisesRegex(ExxError, "B unavailable"):
            compile_body("B example()", "B$0 = 1; return B")

    def test_bit_test_updates_flags_and_preserves_carry(self):
        signature = "CF example(p: HDR → IY, c → CF) clobbers(S, Z, HF, PV, N)"
        plain = compile_body(signature, "if (p->flags$7) return c; return 0")
        self.assertEqual((plain[0].mnemonic, plain[0].reads, plain[0].writes),
                         ("bit", {"IY"}, FLAGS - {"CF"}))
        for condition in ("p->flags$7 == true", "false != p->flags$7", "!(p->flags$7 == 0)"):
            self.assertEqual(compile_body(signature, f"if ({condition}) return c; return 0"), plain)

    def test_mask_precedence_and_complement(self):
        code = compile_body("A example(x → A) clobbers(F)",
                            "x = x & (1 | 2 ^ 7 & 4); x |= 1 << 2 + 1; x = ~x; return x")
        self.assertEqual([(ins.mnemonic, ins.operands) for ins in code],
                         [("and", ("7",)), ("or", ("8",)), ("cpl", ()), ("ret", ())])
        self.assertEqual(code[2].writes, {"A", "HF", "N"})
        masks = compile_body("HL example(x → A) clobbers(A, F)", "x &= ~0x80; return ~0xff")
        self.assertEqual(masks[0].operands, ("127",))
        self.assertEqual(masks[1].operands, ("hl", "65280"))

    def test_shifts_and_rotations(self):
        for operation, mnemonic, needs_carry in (
            ("x <<= 2", "sla", False), ("x >>= 2", "srl", False),
            ("sra(x, 2)", "sra", False),
            ("rlc(x, 2)", "rlc", False), ("rrc(x, 2)", "rrc", False),
            ("rl(x, 2)", "rl", True), ("rr(x, 2)", "rr", True),
        ):
            with self.subTest(operation=operation):
                code = compile_body("D example(x → D, c → CF) clobbers(F)", operation + "; return x")
                self.assertEqual([ins.mnemonic for ins in code], [mnemonic, mnemonic, "ret"])
                self.assertEqual(code[0].reads, {"D", "CF"} if needs_carry else {"D"})
                self.assertEqual(code[0].writes, FLAGS | {"D"})
        zero = compile_body("D example(x → D)", "x >>= 0; return x")
        self.assertEqual([ins.mnemonic for ins in zero], ["ret"])
        word = compile_body("HL example(x → HL) clobbers(CF, HF, N)", "x <<= 1; return x")
        self.assertEqual((word[0].mnemonic, word[0].operands), ("add", ("hl", "hl")))

    def test_adc_sbc_effects_and_operands(self):
        for mnemonic in ("adc", "sbc"):
            for dst, src in (("A", "B"), ("HL", "DE")):
                with self.subTest(mnemonic=mnemonic, dst=dst):
                    code = compile_body(f"{dst} example(x → {dst}, y → {src}, c → CF) clobbers(F)",
                                        f"{mnemonic}(x, y); return x")
                    self.assertEqual((code[0].mnemonic, code[0].operands, code[0].reads),
                                     (mnemonic, (dst.lower(), src.lower()), set(dst + src) | {"CF"}))
                    self.assertEqual(code[0].writes, FLAGS | set(dst))
        with self.assertRaisesRegex(ExxError, "CF unavailable"):
            compile_body("A example(x → A) clobbers(F)", "adc(x, 1); return x")

    def test_rejects_unsupported_forms(self):
        for statement in ("A$8 = 1", "A$B = true", "A$2 = 2", "HL$2 = true",
                          "HL >>= 1", "B <<= -1", "B >>= A", "rlc(B, 256)",
                          "B = ~B", "sbc(DE, HL)"):
            with self.subTest(statement=statement), self.assertRaises(ExxError):
                compile_body("example(a → A, b → B, p → HL) clobbers(A, B, HL, F)", statement)
