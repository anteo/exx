from contextlib import redirect_stderr
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from exxlang.cli import main
from exxlang.compiler import compile_source
from exxlang.diagnostics import ExxError
from exxlang.emit import Assembler
from exxlang.platforms.z80 import Z80
from exxlang.registry import platforms, targets


class RegistryTests(unittest.TestCase):
    def test_registered_classes_drive_cli_and_analysis(self):
        # This platform spells conditional jumps differently but has the same edges.
        class RelativeZ80(Z80):
            name = "relative"

            def branch(self, *args, **kwargs):
                return tuple(replace(ins, mnemonic="jr") if ins.branch_target else ins
                             for ins in super().branch(*args, **kwargs))

        class Listing(Assembler):
            name = "listing"
            platforms = ("relative",)

            def header(self, procedures, section):
                return ["; custom listing"]

        platforms.names()
        targets.names()
        with patch.dict(platforms.classes), patch.dict(targets.classes), TemporaryDirectory() as directory:
            platforms.register(RelativeZ80)
            targets.register(Listing)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                targets.register(Listing)
            source = Path(directory) / "main.exx"
            output = source.with_suffix(".asm")
            source.write_text("A pick(flag → CF) { if (flag) return 1; return 2 }")
            args = ["--target", "listing", str(source), "-o", str(output)]
            self.assertEqual(main(args), 0)
            self.assertIn("; custom listing", output.read_text())
            self.assertIn("jr nc,", output.read_text())
            with redirect_stderr(StringIO()) as message:
                self.assertEqual(main([*args, "--platform", "z80"]), 1)
            self.assertIn("does not support", message.getvalue())
            with self.assertRaisesRegex(ExxError, "A unavailable"):
                compile_source("A pick(flag → CF) { if (flag) { A = 1 }; return A }",
                               platform="relative")
