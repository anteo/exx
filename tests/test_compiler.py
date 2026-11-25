from textwrap import dedent
import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError


def compile_text(source):
    return compile_source(dedent(source).lstrip("\n"))


def instructions(procedure):
    return [(item.mnemonic, item.operands) for item in procedure.instructions]


class CompilerTests(unittest.TestCase):
    def test_unmodelled_registers_cannot_be_used_as_symbolic_immediates(self):
        for name in ("I", "R", "IXH", "IYL"):
            with self.subTest(name=name), self.assertRaisesRegex(ExxError, "unsupported Z80 register"):
                compile_text(f"read() → A {{ return {name} }}")

    def test_parenthesized_load_in_condition_matches_explicit_load(self):
        for control in ("if", "while"):
            start = "pick(ctx: CTX → IX) → A clobbers(F) { value → A; "
            end = " return 1; return 0 }"
            compact, = compile_text(start + control + " ((value = ctx->action) == ACTION)" + end)
            explicit, = compile_text(start + "value = ctx->action; " + control + " (value == ACTION)" + end)
            self.assertEqual(compact.instructions, explicit.instructions)
        with self.assertRaises(ExxError):
            compile_text("pick(x → B) → A clobbers(F) { if (A = x) return 1; return 0 }")

    def test_short_circuit_can_skip_assignment(self):
        for op in ("&&", "||"):
            with self.subTest(op=op), self.assertRaisesRegex(ExxError, "A unavailable"):
                compile_text(f"pick(flag → Z) → A clobbers(F) {{ if (flag {op} (A = 1)) {{}}; return A }}")

    def test_comparison_preserves_left_operand(self):
        with self.assertRaisesRegex(ExxError, "overwrites the left operand"):
            compile_text("pick(a → A, b → B) clobbers(A, F) { if (a == (a = b)) return }")

    def test_assembler_expression_remains_an_immediate(self):
        proc, = compile_text("value() → A { return OFFSET + 1 }")
        self.assertEqual(instructions(proc)[0], ("ld", ("a", "0 + (OFFSET + 1)")))

    def test_stack_pointer_cannot_be_transferred_by_call_contract(self):
        with self.assertRaisesRegex(ExxError, "SP is reserved"):
            compile_text("extern unsafe() clobbers(SP)")

    def test_capture_uses_physical_locations_without_moves(self):
        procedure, = compile_text("""
            extern read(source → E) → (A, HL, DE)
            example(source → E) → (A, HL, DE) {
                (status, cursor, remaining) → (A, HL, DE)
                (status, cursor, remaining) = read(source)
                return (status, cursor, remaining)
            }
        """)
        self.assertEqual(instructions(procedure), [("call", ("read",)), ("ret", ())])
        self.assertEqual(procedure.externals, {"read"})

    def test_capture_requires_all_results_in_abi_order(self):
        for capture in ("A", "(A, HL)", "(A, DE, HL)"):
            with self.subTest(capture=capture):
                with self.assertRaisesRegex(ExxError, r"read returns \(A, HL, DE\)"):
                    compile_text(f"""
                        extern read() → (A, HL, DE)
                        example() → (A, HL, DE) {{
                            {capture} = read()
                            return (A, HL, DE)
                        }}
                    """)

    def test_calls_require_explicit_argument_register_moves(self):
        with self.assertRaisesRegex(ExxError, "source expects E, got D"):
            compile_text("""
                extern advance(source → E)
                example(source → D) {
                    advance(source)
                }
            """)

        procedure, = compile_text("""
            extern advance(source → E)
            example(source → D) clobbers(E) {
                E = source
                advance(E)
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("ld", ("e", "d")), ("call", ("advance",)), ("ret", ()),
        ])

    def test_input_register_and_flag_are_separate_locations(self):
        procedure, = compile_text("""
            example(byte → C, carry → CF) → (C, CF) {
                return (byte, carry)
            }
        """)
        self.assertEqual(instructions(procedure), [("ret", ())])

    def test_abi_groups_reject_overlapping_registers(self):
        with self.assertRaisesRegex(ExxError, "overlapping ABI locations at E"):
            compile_text("extern advance(pointer → DE, byte → E)")
        with self.assertRaisesRegex(ExxError, "overlapping ABI locations at Z"):
            compile_text("extern advance() → (AF, Z)")

    def test_clobber_invalidates_the_affected_part_of_a_pair(self):
        with self.assertRaisesRegex(ExxError, r"D unavailable"):
            compile_text("""
                extern work() clobbers(D)
                example(pointer → DE) → DE {
                    work()
                    return pointer
                }
            """)

        procedure, = compile_text("""
            extern work() clobbers(D)
            example(pointer → DE) → DE {
                work()
                D = 0
                return pointer
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("call", ("work",)), ("ld", ("d", "0")), ("ret", ()),
        ])

    def test_undeclared_call_clobber_is_a_source_error(self):
        with self.assertRaisesRegex(ExxError, "undeclared clobber: E") as error:
            compile_text("""
                extern work() clobbers(E)
                example() {
                    work()
                }
            """)
        self.assertEqual(error.exception.line, 3)

    def test_return_schedules_reg_moves_without_destroying_a_source(self):
        procedure, = compile_text("""
            shuffle(first → A, second → E) → (A, B) {
                return (second, first)
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("ld", ("b", "a")), ("ld", ("a", "e")), ("ret", ()),
        ])
        with self.assertRaisesRegex(ExxError, "return values overlap"):
            compile_text("""
                swap(first → A, second → B) → (A, B) {
                    return (second, first)
                }
            """)

    def test_return_checks_value_count(self):
        with self.assertRaisesRegex(ExxError, "expected 2 return values"):
            compile_text("example(input → A) → (A, CF) { return input }")

    def test_tail_call_checks_output_locations_and_emits_jump(self):
        procedure, = compile_text("""
            extern read(source → E) → (A, HL, DE)
            forward(source → E) → (A, HL, DE) {
                return read(source)
            }
        """)
        self.assertEqual(instructions(procedure), [("jp", ("read",))])

        with self.assertRaisesRegex(ExxError, "tail call to read has incompatible results"):
            compile_text("""
                extern read(source → E) → (A, HL, DE)
                forward(source → E) → (A, DE, HL) {
                    return read(source)
                }
            """)

    def test_all_reachable_paths_produce_results(self):
        with self.assertRaisesRegex(ExxError, "can reach the end without returning"):
            compile_text("""
                example(carry → CF) → A {
                    if (carry) return 1
                }
            """)

        procedure, = compile_text("""
            example(carry → CF) → A {
                if (carry) return 1
                else return 0
            }
        """)
        result = instructions(procedure)
        self.assertIn(("ld", ("a", "1")), result)
        self.assertIn(("ld", ("a", "0")), result)

    def test_assignment_in_loop_is_not_guaranteed_after_loop(self):
        with self.assertRaisesRegex(ExxError, "H, L unavailable"):
            compile_text("""
                example(count → A) → (A, HL) clobbers(F) {
                    while (count) {
                        HL = 0
                        count -= 1
                    }
                    return (count, HL)
                }
            """)

        procedure, = compile_text("""
            example(count → A) → (A, HL) clobbers(F) {
                HL = 0
                while (count) {
                    HL += 1
                    count -= 1
                }
                return (count, HL)
            }
        """)
        self.assertIn(("inc", ("hl",)), instructions(procedure))

    def test_field_access_keeps_symbolic_layout(self):
        procedure, = compile_text("""
            lookup(context: VID_CTX → IY) → A {
                A = context->config
                return A
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("ld", ("a", "(iy + VID_CTX.config)")), ("ret", ()),
        ])
        with self.assertRaisesRegex(ExxError, "field access requires a typed IX or IY binding"):
            compile_text("lookup(context → IY) → A { return context->config }")

    def test_block_binding_does_not_escape_its_scope(self):
        with self.assertRaisesRegex(ExxError, "unknown name result"):
            compile_text("""
                example(carry → CF, input → A) → A {
                    if (carry) { result → A }
                    return result
                }
            """)

    def test_flag_test_does_not_read_or_change_the_accumulator(self):
        procedure, = compile_text("""
            example(zero → Z) → A {
                if (zero) return 1
                return 0
            }
        """)
        ops = instructions(procedure)
        self.assertTrue(any(op == "jp" and args[0] in ("z", "nz") for op, args in ops))
        self.assertNotIn(("or", ("a",)), ops)

    def test_accumulator_test_requires_permission_to_change_flags(self):
        with self.assertRaisesRegex(ExxError, "undeclared clobber: CF"):
            compile_text("""
                example(input → A) → A {
                    if (!input) return 1
                    return input
                }
            """)


if __name__ == "__main__":
    unittest.main()
