from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from exxlang.cli import main
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


class AbiUseTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        return file

    def test_cli_combines_relative_transitive_uses_and_explicit_abi(self):
        self.write("abi/common.abi", "const PAGE = 6\nextern A read_page(page → E)\n")
        video = self.write("abi/video.abi", 'use "common.abi"\n')
        self.write("abi/console abi.abi", 'use "./common.abi"\nconst PAGE_OFFSET = 1\n')
        source = self.write("code/caller.exx", '''
use {
    "../abi/video.abi"
    "../abi/console abi.abi"
}
A fetch_page() clobbers(E) {
    E = PAGE + PAGE_OFFSET
    return read_page(E)
}
''')
        output = self.root / "caller.asm"
        status = main([str(source), "--target", "z80asm", "--abi", str(video), "-o", str(output)])
        self.assertEqual(status, 0)
        assembly = output.read_text(encoding="utf-8")
        self.assertIn("EXTERN read_page", assembly)
        self.assertIn("ld e, 7\n    jp read_page", assembly)
        self.assertNotIn("INCLUDE", assembly)

    def test_missing_nested_abi_names_the_import_site(self):
        interface = self.write("abi/video.abi", '\nuse "missing.abi"')
        with self.assertRaisesRegex(ExxError, "cannot load ABI 'missing.abi'") as error:
            compile_source('use "abi/video.abi"', source_path=self.root / "main.exx")
        self.assertEqual((error.exception.source, error.exception.line), (interface, 2))

    def test_cyclic_import_reports_the_chain(self):
        self.write("one.abi", 'use "two.abi"')
        second = self.write("two.abi", 'use "one.abi"')
        with self.assertRaisesRegex(ExxError, "cyclic ABI import: .*one.abi.*two.abi.*one.abi") as error:
            compile_source('use "one.abi"', source_path=self.root / "main.exx")
        self.assertEqual((error.exception.source, error.exception.line), (second, 1))

    def test_conflicts_name_both_declarations(self):
        for first, second, diagnostic in (
            ("extern A read()", "extern HL read()", "incompatible ABI"),
            ("extern data status: u8", "extern data status: u16", "conflicting data type"),
            ("const SIZE = 1", "const SIZE = 2", "conflicting constant"),
            ("layout CELL: 1", "layout CELL: 2", "conflicting layout size"),
            ("field CELL.attr: u8", "field CELL.attr: u16", "conflicting field type"),
        ):
            with self.subTest(first=first, second=second):
                previous = self.write("one.abi", f"\n{first}\n")
                conflict = self.write("two.abi", f"{second}\n")
                with self.assertRaisesRegex(ExxError, diagnostic) as error:
                    compile_source('use { "one.abi", "two.abi" }', source_path=self.root / "main.exx")
                self.assertEqual((error.exception.source, error.exception.line), (conflict, 1))
                self.assertIn(f"{previous}:2", error.exception.message)

    def test_cli_will_not_overwrite_an_imported_abi(self):
        declarations = "extern A read()\n"
        interface = self.write("video.abi", declarations)
        source = self.write("caller.exx", 'use "video.abi"\nA caller() { return read() }\n')
        error = StringIO()
        with redirect_stderr(error):
            self.assertEqual(main([str(source), "--target", "asm", "-o", str(interface)]), 1)
        self.assertIn("output must be a different file", error.getvalue())
        self.assertEqual(interface.read_text(encoding="utf-8"), declarations)
