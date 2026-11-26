"""Compare the EXX command-line output with the expected assembly text."""

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"


class GoldenAssemblyTests(unittest.TestCase):
    maxDiff = None

    def test_examples(self):
        sources = sorted((ROOT / "examples").glob("*.exx"))
        self.assertTrue(sources, "no .exx examples found")
        for target in ("asm", "z80asm"):
            for source in sources:
                expected = GOLDEN / target / source.with_suffix(".asm").name
                with self.subTest(source=source.name, target=target):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "exx"), "--target", target, str(source)],
                        capture_output=True, encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertMultiLineEqual(expected.read_text(encoding="utf-8"), result.stdout)

    def test_custom_indent_applies_to_generated_lines_only(self):
        source = """struct CELL { value: u8 }
const LIMIT = 5
origin 0x8000
data status: u8 = LIMIT
A read_value() {
    // Keep the assembly block as written.
    asm {
      nop
    }
    return LIMIT
}
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "indent.exx"
            path.write_text(source, encoding="utf-8")
            for target, directives in (
                ("asm", ("LIMIT EQU 5",)),
                ("sjasmplus", ("  STRUCT @CELL", "value BYTE", "  ENDS")),
                ("z80asm", ("  SECTION code_user", "  DEFC LIMIT = 5",
                            "  DEFVARS 0 {", "    CELL_value DS.B 1")),
            ):
                with self.subTest(target=target):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "exx"), "--target", target, "--indent=2",
                         "--include", "shared.inc", str(path)],
                        capture_output=True, encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for line in ('  INCLUDE "shared.inc"', "  ORG 32768", "status:", "  defb 5",
                                 "read_value:", "  ; Keep the assembly block as written.",
                                 "      nop", "  ld a, 5", "  ret", *directives):
                        self.assertIn(line, result.stdout.splitlines())
