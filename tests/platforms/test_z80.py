import unittest

from exxlang.platforms import z80


class Z80Tests(unittest.TestCase):
    def test_load_from_indexed_storage_preserves_flags(self):
        field = z80.Operand("mem", "IX + VID_SESSION.action", 8)
        instructions = z80.move(z80.register("A"), field)
        self.assertEqual(
            instructions,
            (z80.Instruction("ld", ("a", "(ix + VID_SESSION.action)"),
                             frozenset(("IX",)), frozenset(("A",))),),
        )

    def test_field_operand_requires_an_index_register(self):
        self.assertTrue(z80.supports_layout("IX"))
        self.assertTrue(z80.supports_layout("IY"))
        self.assertFalse(z80.supports_layout("HL"))
        self.assertEqual(z80.field_operand("IY", "VID_CTX", "config"),
                         z80.Operand("mem", "IY + VID_CTX.config", 8))
        with self.assertRaises(z80.TargetError):
            z80.field_operand("HL", "VID_CTX", "config")

    def test_rejects_invalid_loads_before_assembly(self):
        for destination, source in (
            (z80.register("HL"), z80.register("DE")),
            (z80.register("F"), z80.register("A")),
            (z80.register("E"), z80.Operand("mem", "BC", 8)),
            (z80.register("A"), z80.Operand("mem", "IX + 128", 8)),
            (z80.register("A"), z80.Operand("imm", "256")),
        ):
            with self.subTest(destination=destination, source=source):
                with self.assertRaises(z80.TargetError):
                    z80.move(destination, source)

    def test_no_op_register_copy(self):
        page = z80.register("DE")
        self.assertEqual(z80.move(page, page), ())

    def test_overlap_resources(self):
        self.assertEqual(z80.resources("DE"), frozenset(("D", "E")))
        self.assertEqual(z80.resources("F"), z80.FLAGS)
        self.assertEqual(z80.resources("AF"), z80.FLAGS | {"A"})
        self.assertEqual(z80.resources("CF") & z80.resources("C"), frozenset())

    def test_xor_writes_accumulator_and_flags(self):
        instructions = z80.binary(z80.register("A"), "^=", z80.register("E"))
        self.assertEqual(
            instructions,
            (z80.Instruction("xor", ("e",), frozenset(("A", "E")), z80.FLAGS | {"A"}),),
        )

    def test_clear_carry_keeps_sign_zero_and_parity(self):
        instructions = z80.move(z80.register("CF"), z80.Operand("imm", "0"))
        self.assertEqual([item.mnemonic for item in instructions], ["scf", "ccf"])
        self.assertEqual(set.union(*(set(item.writes) for item in instructions)), {"CF", "HF", "N"})
        self.assertEqual(set.union(*(set(item.reads) for item in instructions)), {"CF"})

    def test_constant_return_has_no_incoming_accumulator_dependency(self):
        outputs = ("CF", "A")
        zero, one = z80.Operand("imm", "0"), z80.Operand("imm", "1")
        writable = z80.FLAGS | {"A"}
        clear_a = z80.Instruction("xor", ("a",), writes=writable)
        increment = z80.Instruction("inc", ("a",), frozenset(("A",)), writable - {"CF"})
        self.assertEqual(z80.constant_return(outputs, (zero, zero), writable), (clear_a,))
        self.assertEqual(z80.constant_return(outputs, (zero, one), writable), (clear_a, increment))
        self.assertIsNone(z80.constant_return(outputs, (zero, one), writable - {"Z"}))
        self.assertIsNone(z80.constant_return(outputs, (one, zero), writable))

    def test_condition_uses_existing_flag_or_tests_accumulator(self):
        on_zero = z80.branch(z80.register("Z"), None, None, "target")
        self.assertEqual(on_zero, (z80.Instruction("jp", ("z", "target"), frozenset(("Z",)), branch_target="target"),))

        not_accumulator = z80.branch(z80.register("A"), None, None, "target", when_true=False)
        self.assertEqual(not_accumulator[0], z80.Instruction("or", ("a",), frozenset(("A",)), z80.FLAGS))
        self.assertEqual(not_accumulator[1], on_zero[0])

    def test_unsigned_comparison_can_reverse_operands(self):
        accumulator = z80.register("A")
        page = z80.register("E")
        compare = z80.Instruction("cp", ("e",), frozenset(("A", "E")), z80.FLAGS)
        instructions = z80.branch(accumulator, "<", page, "target")
        self.assertEqual(instructions, (compare, z80.Instruction("jp", ("c", "target"), frozenset(("CF",)), branch_target="target")))
        self.assertEqual(instructions, z80.branch(page, ">", accumulator, "target"))

        greater = z80.branch(accumulator, ">", page, "target", new_label=lambda: "skip")
        self.assertEqual(greater, (
            compare,
            z80.Instruction("jp", ("c", "skip"), frozenset(("CF",)), branch_target="skip"),
            z80.Instruction("jp", ("nz", "target"), frozenset(("Z",)), branch_target="target"),
            z80.Instruction("label", ("skip",)),
        ))
        self.assertEqual(greater, z80.branch(page, "<", accumulator, "target", new_label=lambda: "skip"))

        at_most = z80.branch(accumulator, ">", page, "target", when_true=False)
        self.assertEqual(at_most, (
            compare,
            z80.Instruction("jp", ("c", "target"), frozenset(("CF",)), branch_target="target"),
            z80.Instruction("jp", ("z", "target"), frozenset(("Z",)), branch_target="target"),
        ))

    def test_comparison_rejects_implicit_accumulator_use(self):
        with self.assertRaisesRegex(z80.TargetError, "requires an accumulator"):
            z80.branch(z80.register("C"), "<", z80.register("D"), "target")

    def test_compaction_folds_early_return_with_an_unshared_label(self):
        condition = z80.Instruction("jp", ("nc", "exx__after"), frozenset(("CF",)))
        ret = z80.Instruction("ret", reads=frozenset(("A",)))
        after = z80.Instruction("label", ("exx__after",))
        last = z80.Instruction("ret")
        self.assertEqual(
            z80.compact([condition, ret, after, last]),
            (z80.Instruction("ret", ("c",), frozenset(("CF", "A"))), last),
        )

    def test_compaction_retains_shared_labels_and_edits_only_fallthrough_jumps(self):
        after = z80.Instruction("label", ("exx__after",))
        entry = z80.Instruction("label", ("entry",))
        unused = z80.Instruction("label", ("exx__unused",))
        reference = z80.Instruction("ld", ("hl", "exx__after + 1"))
        forward = z80.Instruction("jp", ("z", "exx__after"))
        to_after = z80.Instruction("jp", ("exx__after",))
        self.assertEqual(
            z80.compact([forward, reference, to_after, unused, entry, after]),
            (forward, reference, entry, after),
        )

    def test_compaction_retains_a_shared_early_return_label(self):
        condition = z80.Instruction("jp", ("nc", "exx__after"), frozenset(("CF",)))
        ret = z80.Instruction("ret")
        after = z80.Instruction("label", ("exx__after",))
        back = z80.Instruction("jp", ("exx__after",))
        self.assertEqual(
            z80.compact([condition, ret, after, back]),
            (z80.Instruction("ret", ("c",), frozenset(("CF",))), after, back),
        )
