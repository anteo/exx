import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError


def assembly(source):
    proc, = compile_source(source)
    return [(ins.mnemonic, ins.operands) for ins in proc.instructions]


class KeepTests(unittest.TestCase):
    def test_save_order_aliases_and_conditional_return(self):
        code = assembly("f(count → BC, carry → CF) { keep(count, AF) { "
                        "if (carry) return; B = 3 } }")
        self.assertEqual(code, [
            ("push", ("bc",)), ("push", ("af",)), ("jp", ("nc", "exx__f_1")),
            ("pop", ("af",)), ("pop", ("bc",)), ("ret", ()),
            ("label", ("exx__f_1",)), ("ld", ("b", "3")),
            ("pop", ("af",)), ("pop", ("bc",)), ("ret", ()),
        ])

    def test_break_unwinds_only_exited_scopes(self):
        code = assembly("f(flag → CF) { keep(BC) { while (flag) { "
                        "keep(DE) { if (flag) break; D = 3 } } } }")
        self.assertEqual(code.count(("pop", ("bc",))), 1)
        self.assertEqual(code.count(("pop", ("de",))), 2)
        self.assertIn([("pop", ("de",)), ("jp", ("exx__f_2",))],
                      [code[i:i + 2] for i in range(len(code))])

    def test_return_checks_only_live_parts(self):
        assembly("f(x → B) → B { keep(BC) { C = 3; return x } }")
        assembly("f() → A { A = 7; keep(AF) { keep(AF) { A = 3 }; return A } }")
        assembly("f() → B { keep(AF) { A = 3; return A } }")
        for body in ("A = 3; return A", "if (flag) { A = 3 }; return A"):
            with self.subTest(body=body), self.assertRaisesRegex(ExxError, "keep.*live A"):
                assembly("f(x → A, flag → CF) → A { keep(AF) { " + body + " } }")
        with self.assertRaisesRegex(ExxError, "keep.*live CF"):
            assembly("f(x → A) → CF { keep(AF) { x += 1; return CF } }")

    def test_tail_call_restores_before_jump(self):
        prefix = "extern next(x → A) → A\nf(x → A) → A { keep(AF) { "
        code = assembly(prefix + "return next(x) } }")
        self.assertEqual(code, [("push", ("af",)), ("pop", ("af",)), ("jp", ("next",))])
        with self.assertRaisesRegex(ExxError, "keep.*live A"):
            assembly(prefix + "x = 7; return next(x) } }")

    def test_manual_stack_cannot_consume_keep_slots(self):
        assembly("f() { keep(BC) { push(DE); ex_sp(HL); ex_sp(HL); pop(DE) } }")
        for body in ("pop(BC); push(BC)", "ex_sp(HL)", "push(DE); return"):
            with self.subTest(body=body), self.assertRaisesRegex(ExxError, "keep save"):
                assembly("f() { keep(BC) { " + body + " } }")

    def test_rejects_invalid_saves(self):
        for args in ("", "A", "SP", "IX + 1"):
            with self.subTest(args=args), self.assertRaises(ExxError):
                assembly(f"f() {{ keep({args}) {{ }} }}")
