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
                compile_text(f"A read() {{ return {name} }}")

    def test_parenthesized_load_in_condition_matches_explicit_load(self):
        for control in ("if", "while"):
            start = "A pick(ctx: CTX → IX) clobbers(F) { value → A; "
            end = " return 1; return 0 }"
            compact, = compile_text(start + control + " ((value = ctx->action) == ACTION)" + end)
            explicit, = compile_text(start + "value = ctx->action; " + control + " (value == ACTION)" + end)
            self.assertEqual(compact.instructions, explicit.instructions)
        with self.assertRaises(ExxError):
            compile_text("A pick(x → B) clobbers(F) { if (A = x) return 1; return 0 }")

    def test_short_circuit_can_skip_assignment(self):
        for op in ("&&", "||"):
            with self.subTest(op=op), self.assertRaisesRegex(ExxError, "A unavailable"):
                compile_text(f"A pick(flag → Z) clobbers(F) {{ if (flag {op} (A = 1)) {{}}; return A }}")

    def test_comparison_preserves_left_operand(self):
        with self.assertRaisesRegex(ExxError, "overwrites the left operand"):
            compile_text("pick(a → A, b → B) clobbers(A, F) { if (a == (a = b)) return }")

    def test_prefix_and_postfix_updates_order_the_load_in_a_comparison(self):
        for op, mnemonic in (("++", "inc"), ("--", "dec")):
            for expr, prefix in ((f"{op}column", True), (f"column{op}", False)):
                with self.subTest(expr=expr):
                    proc, = compile_text(f"""
                        (CF, BC) next(cursor → BC, columns → E) clobbers(A, F) {{
                            column → C
                            if ((A = {expr}) < columns) return (CF, cursor)
                            column = 0
                            return (CF, cursor)
                        }}
                    """)
                    update = (mnemonic, ("c",))
                    load = ("ld", ("a", "c"))
                    expected = [update, load] if prefix else [load, update]
                    self.assertEqual(instructions(proc)[:4], expected + [("cp", ("e",)), ("ret", ("c",))])

    def test_updates_preserve_carry_and_handle_byte_and_word_registers(self):
        proc, = compile_text("""
            (A, HL, CF) step(byte → A, word → HL, carry → CF) clobbers(S, Z, HF, PV, N) {
                ++byte
                word--
                return (byte, word, carry)
            }
        """)
        self.assertEqual(instructions(proc), [("inc", ("a",)), ("dec", ("hl",)), ("ret", ())])

    def test_updates_require_registers_and_preserve_live_operands(self):
        for source, diagnostic in (
            ("f() { ++1 }", "requires a register or register alias"),
            ("f(p → HL) { (*p)++ }", "requires a register or register alias"),
            ("A f(a → A) clobbers(F) { a = a++; return a }", "requires a separate register"),
            ("f(a → A, b → B) clobbers(B, F) { if (a < b++) return }", "separate register"),
            ("A f(a → A) clobbers(F) { a = a + ++a; return a }", "overwrites the left operand"),
            ("f(a → A) clobbers(F) { ++a }", "clobber"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_text(source)

    def test_arithmetic_assignments_use_the_explicit_registers(self):
        proc, = compile_text("""
            (IY, DE) adjust(base → IY) clobbers(CF, HF, N) {
                base += (DE = OFFSET + RST8_DATA_OFF)
                return (base, DE)
            }
        """)
        self.assertEqual(instructions(proc), [
            ("ld", ("de", "0 + (OFFSET + RST8_DATA_OFF)")),
            ("add", ("iy", "de")), ("ret", ()),
        ])
        proc, = compile_text("A f() clobbers(B, F) { A = (A = 1) + (B = 2); return A }")
        self.assertEqual(instructions(proc), [
            ("ld", ("a", "1")), ("ld", ("b", "2")), ("add", ("a", "b")), ("ret", ()),
        ])

    def test_nested_arithmetic_assignment_preserves_inputs_and_addresses(self):
        for source in (
            "HL f(base → HL) clobbers(F) { base += (HL = 2); return HL }",
            "f(base → IX) clobbers(IX) { base[0] = (IX = 1) }",
            "A f(value → A) clobbers(F) { A = value - (A = 1); return A }",
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, "overwrites the left operand"):
                compile_text(source)

    def test_forward_and_backward_goto_use_local_branches(self):
        proc, = compile_text("""
            A f(ready → Z) {
            again:
                if (ready) goto again
                goto done
                A = 2
            done:
                return 1
            }
        """)
        self.assertEqual(instructions(proc), [
            ("label", ("exx__f_1",)), ("jr", ("z", "exx__f_1")),
            ("ld", ("a", "1")), ("ret", ()),
        ])

    def test_goto_unwinds_keep_blocks(self):
        proc, = compile_text("""
            f() {
                keep(BC) {
                    B = 1
                    keep(DE) {
                        D = 2
                        goto done
                    }
                }
            done:
                return
            }
        """)
        self.assertEqual(instructions(proc), [
            ("push", ("bc",)), ("ld", ("b", "1")), ("push", ("de",)), ("ld", ("d", "2")),
            ("pop", ("de",)), ("pop", ("bc",)), ("ret", ()),
        ])

    def test_goto_checks_scope_and_flow_at_its_target(self):
        for source, diagnostic in (
            ("f() { goto absent }\nabsent() {}", "unknown label"),
            ("f() { here: here: return }", "duplicate label"),
            ("f() { goto inside; keep(BC) { inside: B = 1 } }", "cannot enter"),
            ("A f(flag → CF) { if (flag) goto done; A = 1; done: return A }", "A unavailable"),
            ("f(flag → CF) { if (flag) goto done; push(BC); done: return }", "different stack depths"),
        ):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, diagnostic):
                compile_text(source)

    def test_assembler_expression_remains_an_immediate(self):
        proc, = compile_text("A value() { return OFFSET + 1 }")
        self.assertEqual(instructions(proc)[0], ("ld", ("a", "0 + (OFFSET + 1)")))

    def test_stack_pointer_cannot_be_transferred_by_call_contract(self):
        with self.assertRaisesRegex(ExxError, "SP is reserved"):
            compile_text("extern unsafe() clobbers(SP)")

    def test_capture_uses_physical_locations_without_moves(self):
        procedure, = compile_text("""
            extern (A, HL, DE) read(source → E)
            (A, HL, DE) example(source → E) {
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
                        extern (A, HL, DE) read()
                        (A, HL, DE) example() {{
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
            (C, CF) example(byte → C, carry → CF) {
                return (byte, carry)
            }
        """)
        self.assertEqual(instructions(procedure), [("ret", ())])

    def test_abi_groups_reject_overlapping_registers(self):
        with self.assertRaisesRegex(ExxError, "overlapping ABI locations at E"):
            compile_text("extern advance(pointer → DE, byte → E)")
        with self.assertRaisesRegex(ExxError, "overlapping ABI locations at Z"):
            compile_text("extern (AF, Z) advance()")

    def test_clobber_invalidates_the_affected_part_of_a_pair(self):
        with self.assertRaisesRegex(ExxError, r"D unavailable"):
            compile_text("""
                extern work() clobbers(D)
                DE example(pointer → DE) {
                    work()
                    return pointer
                }
            """)

        procedure, = compile_text("""
            extern work() clobbers(D)
            DE example(pointer → DE) {
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
            (A, B) shuffle(first → A, second → E) {
                return (second, first)
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("ld", ("b", "a")), ("ld", ("a", "e")), ("ret", ()),
        ])
        with self.assertRaisesRegex(ExxError, "return values overlap"):
            compile_text("""
                (A, B) swap(first → A, second → B) {
                    return (second, first)
                }
            """)

    def test_return_checks_value_count(self):
        with self.assertRaisesRegex(ExxError, "expected 2 return values"):
            compile_text("(A, CF) example(input → A) { return input }")

    def test_tail_call_checks_output_locations_and_emits_jump(self):
        procedure, = compile_text("""
            extern (A, HL, DE) read(source → E)
            (A, HL, DE) forward(source → E) {
                return read(source)
            }
        """)
        self.assertEqual(instructions(procedure), [("jp", ("read",))])

        with self.assertRaisesRegex(ExxError, "tail call to read has incompatible results"):
            compile_text("""
                extern (A, HL, DE) read(source → E)
                (A, DE, HL) forward(source → E) {
                    return read(source)
                }
            """)

    def test_conditional_calls_keep_register_effects_on_the_taken_path(self):
        proc, = compile_text("""
            extern update() clobbers(B)
            f(flag → Z) clobbers(B) { if (flag) update() }
        """)
        self.assertEqual(instructions(proc), [("call", ("z", "update")), ("ret", ())])
        with self.assertRaisesRegex(ExxError, "B unavailable"):
            compile_text("""
                extern update() clobbers(B)
                A f(flag → Z, value → B) clobbers(B) {
                    if (flag) update()
                    return value
                }
            """)
        with self.assertRaisesRegex(ExxError, "B unavailable"):
            compile_text("""
                extern B get()
                A f(flag → Z) clobbers(B) {
                    if (flag) get()
                    return B
                }
            """)

    def test_conditional_tail_call_participates_in_branch_selection(self):
        for provider, op in (("extern A get()", "jp"), ("A get() { return 2 }", "jr")):
            with self.subTest(provider=provider):
                proc = compile_text(provider + "\nA f(flag → Z) { if (flag) return get(); return 1 }")[-1]
                self.assertEqual(instructions(proc), [(op, ("z", "get")), ("ld", ("a", "1")), ("ret", ())])

    def test_conditional_tail_call_leaves_stack_cleanup_on_the_taken_path(self):
        proc, = compile_text("""
            extern next()
            f(flag → Z) { keep(BC) { if (flag) return next(); B = 3 } }
        """)
        code = instructions(proc)
        self.assertIn(("jr", ("nz", "exx__f_1")), code)
        self.assertEqual(code[2:4], [("pop", ("bc",)), ("jp", ("next",))])

    def test_all_reachable_paths_produce_results(self):
        with self.assertRaisesRegex(ExxError, "can reach the end without returning"):
            compile_text("""
                A example(carry → CF) {
                    if (carry) return 1
                }
            """)

        procedure, = compile_text("""
            A example(carry → CF) {
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
                (A, HL) example(count → A) clobbers(F) {
                    while (count) {
                        HL = 0
                        count -= 1
                    }
                    return (count, HL)
                }
            """)

        procedure, = compile_text("""
            (A, HL) example(count → A) clobbers(F) {
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
            A lookup(context: VID_CTX → IY) {
                A = context->config
                return A
            }
        """)
        self.assertEqual(instructions(procedure), [
            ("ld", ("a", "(iy + VID_CTX.config)")), ("ret", ()),
        ])
        with self.assertRaisesRegex(ExxError, "field access requires a typed IX or IY binding"):
            compile_text("A lookup(context → IY) { return context->config }")

    def test_block_binding_does_not_escape_its_scope(self):
        with self.assertRaisesRegex(ExxError, "unknown name result"):
            compile_text("""
                A example(carry → CF, input → A) {
                    if (carry) { result → A }
                    return result
                }
            """)

    def test_flag_test_does_not_read_or_change_the_accumulator(self):
        procedure, = compile_text("""
            A example(zero → Z) {
                if (zero) return 1
                return 0
            }
        """)
        ops = instructions(procedure)
        self.assertTrue(any(op == "jr" and args[0] in ("z", "nz") for op, args in ops))
        self.assertNotIn(("or", ("a",)), ops)

    def test_accumulator_test_requires_permission_to_change_flags(self):
        with self.assertRaisesRegex(ExxError, "undeclared clobber: CF"):
            compile_text("""
                A example(input → A) {
                    if (!input) return 1
                    return input
                }
            """)


if __name__ == "__main__":
    unittest.main()
