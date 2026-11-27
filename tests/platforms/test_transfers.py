import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError


class TransferTests(unittest.TestCase):
    def test_partial_register_and_flags_survive_save_and_call(self):
        src = ("extern run() clobbers(AF, BC)\n"
               "(CF, B) f(c → CF, b → B) { push(AF); push(BC); run(); "
               "pop(BC); pop(AF); return (c, b) }")
        proc, = compile_source(src)
        self.assertEqual([ins.mnemonic for ins in proc.instructions],
                         ["push", "push", "call", "pop", "pop", "ret"])
        with self.assertRaisesRegex(ExxError, "C unavailable"):
            compile_source(src.replace("→ (CF, B)", "→ (CF, C)").replace("return (c, b)", "return (c, C)"))

    def test_reinterpreting_a_stack_word(self):
        compile_source("HL f(x → IX) { push(x); pop(HL); return HL }")
        compile_source("CF f(c → C) clobbers(AF) { push(BC); pop(AF); return CF }")
        with self.assertRaisesRegex(ExxError, "A unavailable"):
            compile_source("A f(c → C) clobbers(AF) { push(BC); pop(AF); return A }")

    def test_preservation_checks_original_contents(self):
        with self.assertRaisesRegex(ExxError, "undeclared clobber"):
            compile_source("f() { push(BC); B = 0; pop(DE) }")
        with self.assertRaisesRegex(ExxError, "undeclared clobber"):
            compile_source("f() clobbers(DE) { push(BC); B = 0; pop(DE) }")
        compile_source("f() { ex(DE, HL); ex(HL, DE) }")
        compile_source("f() { push(BC); ex_sp(IX); ex_sp(IX); pop(BC) }")

    def test_stack_balance_at_branches_loops_and_exits(self):
        for body in ("pop(IX)", "ex_sp(HL)", "push(IX); return",
                     "push(BC); return helper()", "if (flag) {push(BC)}; pop(BC)",
                     "while (flag) {push(BC)}"):
            with self.subTest(body=body), self.assertRaisesRegex(ExxError, "stack|saved word"):
                compile_source("extern helper()\nf(flag → Z) {" + body + "}")
        compile_source("f(flag → Z) { while (flag) {push(BC); pop(BC)} }")

    def test_branch_merge_retains_only_common_saved_values(self):
        compile_source("HL f(flag → Z, a → BC, b → DE) { if (flag) {push(a)} else {push(b)}; pop(HL); return HL }")
        with self.assertRaisesRegex(ExxError, "H, L unavailable"):
            compile_source("HL f(flag → Z, a → BC) { if (flag) {push(a)} else {push(DE)}; pop(HL); return HL }")

    def test_shadow_bank_reads_and_external_clobbers(self):
        compile_source("HL f(saved → HL') clobbers(HL', BC, BC', DE, DE') "
                       "{ exx(); return HL }")
        with self.assertRaisesRegex(ExxError, "A unavailable"):
            compile_source("A f() clobbers(AF, AF') { ex(AF); return A }")
        with self.assertRaisesRegex(ExxError, "undeclared clobber"):
            compile_source("extern work() clobbers(AF')\nf() clobbers(AF') "
                           "{ex(AF); work(); ex(AF)}")

    def test_shadow_pair_locations_in_call_and_asm_contracts(self):
        probe, save = compile_source("""
            extern (DE', HL') read(bank → AF') clobbers(BC')
            (DE', HL') probe(bank → AF') clobbers(BC') { return read(AF') }
            AF' save(value → AF) clobbers(AF) {
                asm(value) → AF' clobbers(AF) { ex af,af' }
            }
        """)
        self.assertEqual(probe.instructions[0].operands, ("read",))
        self.assertIn("A'", save.instructions[0].writes)
        with self.assertRaisesRegex(ExxError, "unknown ABI register HL_ALT"):
            compile_source("f() clobbers(HL_ALT) {}")

    def test_io_checks_full_port_address_and_flags(self):
        with self.assertRaisesRegex(ExxError, "B unavailable"):
            compile_source("A f(c → C) clobbers(F) {A = in(BC); return A}")
        with self.assertRaisesRegex(ExxError, "A unavailable"):
            compile_source("A f() {A = in(0xFE); return A}")
        compile_source("(A, CF) f(high → A, c → CF) {A = in(0xfe); return (A, c)}")
        with self.assertRaisesRegex(ExxError, "CF unavailable"):
            compile_source("CF f(p → HL, port → BC) clobbers(F, HL, B) "
                           "{inir(p, C, B); return CF}")

    def test_block_families(self):
        signature = "f(src → HL, dst → DE, count → BC, needle → A) clobbers(HL, DE, BC, F)"
        for registers, aliases, operations in (
            ("DE, HL, BC", "dst, src, count", ("ldi", "ldir", "ldd", "lddr")),
            ("HL, A, BC", "src, needle, count", ("cpi", "cpir", "cpd", "cpdr")),
            ("HL, C, B", "src, C, B", ("ini", "inir", "ind", "indr")),
            ("C, HL, B", "C, src, B", ("outi", "otir", "outd", "otdr")),
        ):
            for opcode in operations:
                with self.subTest(opcode=opcode):
                    short, = compile_source(f"{signature} {{ {opcode}() }}")
                    self.assertEqual([ins.mnemonic for ins in short.instructions], [opcode, "ret"])
                    for args in (registers, aliases):
                        explicit, = compile_source(f"{signature} {{ {opcode}({args}) }}")
                        self.assertEqual(explicit.instructions, short.instructions)

    def test_fixed_operands_and_arity(self):
        for call in ("ldir(src, dst, count)", "ldir(dst, src)", "ldir(dst, src, count, A)",
                     "cpir(A, HL, BC)", "inir(HL, B, C)", "otir(HL, C, B)",
                     "ex(BC, DE, HL)", "exx(AF)", "ex()", "ex_sp(DE)", "out()", "A = in()"):
            with self.subTest(call=call), self.assertRaisesRegex(ExxError, "expected|unsupported|invalid"):
                compile_source(f"f(src → HL, dst → DE, count → BC, a → A) clobbers(F) {{ {call} }}")

    def test_implicit_operands_follow_register_contract(self):
        for args in ("", "DE, HL, BC"):
            with self.subTest(args=args), self.assertRaisesRegex(ExxError, "B, C unavailable"):
                compile_source(f"f(src → HL, dst → DE) clobbers(BC, F, HL, DE) {{ ldir({args}) }}")
            with self.subTest(args=args), self.assertRaisesRegex(ExxError, "undeclared clobber"):
                compile_source(f"f(src → HL, dst → DE, count → BC) {{ ldir({args}) }}")
