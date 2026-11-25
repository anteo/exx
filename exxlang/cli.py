"""Command-line entry point for EXX."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from .compiler import compile_source
from .diagnostics import ExxError
from .registry import platforms, targets


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
    parser = argparse.ArgumentParser(description="Compile EXX procedures to assembly.")
    parser.add_argument("source", type=Path, help="EXX source file")
    parser.add_argument("--target", required=True, choices=targets.names(), help="assembler dialect")
    parser.add_argument("--platform", choices=platforms.names(), help="CPU (default selected by target)")
    parser.add_argument("--abi", type=Path, action="append", default=[], metavar="FILE",
                        help="shared EXX extern declarations (repeatable)")
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    parser.add_argument("--section", default="code_user", help="section for z80asm output")
    parser.add_argument("--include", action="append", default=[], metavar="PATH",
                        help="assembler include to place before generated procedures")
    args = parser.parse_args(argv)

    try:
        source = args.source.read_text(encoding="utf-8")
        target = targets.create(args.target)
        platform = args.platform or target.platforms[0]
        if platform not in target.platforms:
            raise ValueError(f"{target.name} does not support platform {platform}")
        interfaces = [(path, path.read_text(encoding="utf-8")) for path in args.abi]
        procedures = compile_source(source, platform=platform, interfaces=interfaces)
        assembly = target.emit(procedures, args.section, args.include)
        if args.output is None:
            sys.stdout.write(assembly)
        else:
            output = args.output.resolve()
            if any(output == path.resolve() or (output.exists() and output.samefile(path))
                   for path in [args.source, *args.abi]):
                raise ValueError("output must be a different file from the source and ABI files")
            _write_output(output, assembly)
    except ExxError as error:
        print(f"{error.source or args.source}:{error.line}: error: {error.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"exx: error: {error}", file=sys.stderr)
        return 1
    return 0
