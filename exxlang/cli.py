"""Command-line entry point for EXX."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from .compiler import compile_source
from .emit import TARGETS, emit
from .syntax import ExxError


def _write_output(output: Path, text: str) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile EXX procedures to Z80 assembly.")
    parser.add_argument("source", type=Path, help="EXX source file")
    parser.add_argument("--target", required=True, choices=TARGETS, help="assembler dialect")
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    parser.add_argument("--section", default="code_user", help="section for z88dk output")
    parser.add_argument("--include", action="append", default=[], metavar="PATH",
                        help="assembler include to place before generated procedures")
    args = parser.parse_args(argv)

    try:
        source = args.source.read_text(encoding="utf-8")
        assembly = emit(compile_source(source), args.target, args.section, args.include)
        if args.output is None:
            sys.stdout.write(assembly)
        else:
            output = args.output.resolve()
            if output == args.source.resolve() or (output.exists() and output.samefile(args.source)):
                raise ValueError("output must be a different file from the source")
            _write_output(output, assembly)
    except ExxError as error:
        print(f"{args.source}:{error.line}: error: {error.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"exx: error: {error}", file=sys.stderr)
        return 1
    return 0
