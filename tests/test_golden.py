"""Compare the EXX command-line output with the expected assembly text."""

from pathlib import Path
import subprocess
import sys
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
