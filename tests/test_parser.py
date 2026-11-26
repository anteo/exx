import unittest

from exxlang.diagnostics import ExxError
from exxlang.parser import parse
from exxlang.syntax import Param


class ParserTests(unittest.TestCase):
    def test_extern_and_definition_have_distinct_bodies(self):
        extern, proc, void = parse("extern (CF, A) f(x: T → IX) clobbers(HL)\nA g() {}\nh() {}").procs
        self.assertEqual(extern.params, (Param("x", "IX", "T", 1),))
        self.assertEqual(extern.outputs, ("CF", "A"))
        self.assertEqual(extern.clobbers, ("HL",))
        self.assertIsNone(extern.body)
        self.assertEqual(proc.body, ())
        self.assertEqual(proc.outputs, ("A",))
        self.assertEqual(void.outputs, ())

    def test_legacy_result_suffix_is_rejected(self):
        for arrow in ("→", "->"):
            for source in (f"f() {arrow} A {{ return 0 }}", f"extern f() {arrow} (CF, A)"):
                with self.subTest(source=source), self.assertRaises(ExxError):
                    parse(source)

    def test_result_tuple_requires_multiple_locations(self):
        for source in ("() f() {}", "extern (A) f()"):
            with self.subTest(source=source), self.assertRaisesRegex(ExxError, "at least two"):
                parse(source)

    def test_call_capture_and_field_access(self):
        proc, = parse("f(p: T → IX) { (CF, A) = read(p); return p->value }").procs
        capture, result = proc.body
        self.assertEqual(capture.target.kind, "tuple")
        self.assertEqual([x.value for x in capture.target.args], ["CF", "A"])
        self.assertEqual((capture.value.kind, capture.value.value), ("call", "read"))
        self.assertEqual((result.value.kind, result.value.value), ("field", "value"))
        self.assertEqual(result.value.args[0].value, "p")

    def test_nested_control_flow_and_precedence(self):
        proc, = parse("f() { while (A) { if (!Z || A == B && CF) { return } else { A = 0 } } }").procs
        loop, = proc.body
        branch, = loop.body
        self.assertEqual((loop.kind, branch.kind), ("while", "if"))
        self.assertEqual(branch.value.value, "||")
        left, right = branch.value.args
        self.assertEqual((left.value, right.value, right.args[0].value), ("!", "&&", "=="))
        self.assertEqual(branch.otherwise[0].kind, "assign")

    def test_binding_arity_is_a_grammar_error(self):
        with self.assertRaisesRegex(ExxError, "one register per name") as error:
            parse("f() {\n (left, right) → B\n}")
        self.assertEqual(error.exception.line, 2)
