import unittest

from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError


class InterfaceTests(unittest.TestCase):
    interface = [("video.abi", "extern (A, HL) read(ctx: CTX → IX) clobbers(DE)")]

    def test_compiles_both_sides_with_shared_declarations(self):
        provider, = compile_source(
            "(A, HL) read(arg: CTX → IX) clobbers(D, E) { return (arg->value, 0) }",
            interfaces=self.interface)
        caller, = compile_source(
            "(A, HL) use(src: CTX → IX) clobbers(DE) { return read(src) }",
            interfaces=self.interface)
        self.assertFalse(provider.externals)
        self.assertEqual(caller.externals, {"read"})

    def test_rejects_provider_abi_drift(self):
        for signature in ("arg: OTHER → IX", "arg: CTX → IY"):
            with self.subTest(signature=signature), self.assertRaisesRegex(ExxError, "incompatible ABI"):
                compile_source(f"(A, HL) read({signature}) clobbers(DE) {{}}", interfaces=self.interface)
        for results, clobbers in (("(HL, A)", "DE"), ("(A, HL)", "D")):
            with self.subTest(results=results, clobbers=clobbers):
                with self.assertRaisesRegex(ExxError, "incompatible ABI"):
                    compile_source(f"{results} read(arg: CTX → IX) clobbers({clobbers}) {{}}",
                                   interfaces=self.interface)

    def test_layout_checks_apply_to_raw_register_and_local_alias(self):
        for layout in ("", ": OTHER"):
            for arg in ("IX", "another", "src"):
                with self.subTest(layout=layout, arg=arg), self.assertRaisesRegex(ExxError, "requires layout CTX"):
                    compile_source(f"(A, HL) use(src{layout} → IX) clobbers(DE) "
                                   f"{{ another → IX; return read({arg}) }}", interfaces=self.interface)

    def test_shared_file_diagnostic_names_its_source(self):
        with self.assertRaisesRegex(ExxError, "only contain extern") as error:
            compile_source("", interfaces=[("bad.abi", "\nbody() {}")])
        self.assertEqual((error.exception.source, error.exception.line), ("bad.abi", 2))
