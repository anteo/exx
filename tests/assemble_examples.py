"""Compile the examples, assemble them with both tools, and compare binaries."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "0x8000"

# Match DuoConf's VID_CTX and VID_SESSION layouts and RST8 constants.
VIDEO_CONSTANTS = {
    "VID_CTX.config": 0,
    "VID_CTX.draw": 8,
    "VID_CTX.slot0": 15,
    "VID_CTX.slot1": 22,
    "VID_SESSION.dest": 13,
    "VID_SESSION.action": 14,
    "RST8_VID_NO_WINDOW": 0xFF,
    "RST8_VID_PREP_DRAW": 0x43,
    "RST8_VID_SELECT_DRAW": 0x46,
    "RST8_VID_SHOW_SLOT": 0x47,
}
VIDEO_HELPERS = (
    "video_window_matches",
    "video_plane_conflict",
    "video_stack_safe",
    "video_unavailable",
)


def run(command: list[str], directory: Path) -> None:
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
    if result.returncode:
        details = (result.stdout + result.stderr).rstrip()
        raise RuntimeError(f"{' '.join(command)} exited with {result.returncode}\n{details}")


def assemble(example: Path, target: str, assembler: str, directory: Path) -> bytes:
    directory.mkdir()
    constants = VIDEO_CONSTANTS if example.stem == "video_plan_plane" else {}
    helpers = VIDEO_HELPERS if example.stem == "video_plan_plane" else ()
    command = [
        sys.executable, str(ROOT / "exx"), "--target", target,
        str(example), "-o", "generated.asm",
    ]
    if constants:
        if target == "sjasmplus":
            definitions = [f"{name} equ {value}" for name, value in constants.items()]
        else:
            definitions = [
                f"    DEFC {name.replace('.', '_')} = {value}"
                for name, value in constants.items()
            ]
        (directory / "layout.inc").write_text("\n".join(definitions) + "\n", encoding="ascii")
        command.extend(("--include", "layout.inc"))
    run(command, directory)

    # Fixed-size stubs supply deterministic external addresses to both assemblers.
    stub_code = "".join(f"{name}:\n    ret\n" for name in helpers)
    if target == "sjasmplus":
        wrapper = f'    ORG {ORIGIN}\n    INCLUDE "generated.asm"\n{stub_code}'
        (directory / "wrapper.asm").write_text(wrapper, encoding="ascii")
        run([assembler, "--nologo", "--raw=example.bin", "wrapper.asm"], directory)
    else:
        command = [assembler, "-b", f"-r={ORIGIN}", "-o=example.bin", "generated.asm"]
        if helpers:
            symbols = "".join(f"    PUBLIC {name}\n" for name in helpers)
            (directory / "helpers.asm").write_text(
                f"    SECTION code_user\n{symbols}{stub_code}", encoding="ascii",
            )
            command.append("helpers.asm")
        run(command, directory)
    return (directory / "example.bin").read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sjasmplus", default=os.environ.get("SJASMPLUS", "sjasmplus"))
    parser.add_argument("--z80asm", default=os.environ.get("Z88DK_Z80ASM", "z88dk-z80asm"))
    args = parser.parse_args()
    examples = sorted((ROOT / "examples").glob("*.exx"))
    if not examples:
        parser.error("no EXX examples found")

    try:
        with TemporaryDirectory(prefix="exx-assemble-") as scratch:
            for example in examples:
                binary = assemble(
                    example, "sjasmplus", args.sjasmplus, Path(scratch) / f"{example.stem}-sj",
                )
                linked = assemble(
                    example, "z88dk", args.z80asm, Path(scratch) / f"{example.stem}-z88dk",
                )
                if not binary:
                    raise RuntimeError(f"{example.name}: empty binary")
                if binary != linked:
                    mismatch = next(
                        (i for i, (first, second) in enumerate(zip(binary, linked)) if first != second),
                        min(len(binary), len(linked)),
                    )
                    raise RuntimeError(
                        f"{example.name}: binaries differ at offset {mismatch:#x} "
                        f"(sjasmplus {len(binary)} bytes, z88dk {len(linked)} bytes)"
                    )
                print(f"{example.name}: both assemblers produced the same {len(binary)} bytes")
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
