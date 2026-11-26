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
    if example.stem == "bit_operations":
        constants = {"PACKET.status": 0, "PACKET.flags": 1}
    helpers = VIDEO_HELPERS if example.stem == "video_plan_plane" else ()
    command = [
        sys.executable, str(ROOT / "exx"), "--target", target,
        str(example), "-o", "generated.asm",
    ]
    if constants:
        if target == "asm":
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
    if target == "asm":
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


def assemble_shared_abi(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    (directory / "shared.abi").write_text("extern fetch(arg → B) → A\n")
    (directory / "provider.exx").write_text("fetch(value → B) → A { return value }\n")
    (directory / "caller.exx").write_text("forward(value → B) → A { return fetch(value) }\n")
    for target in ("asm", "z80asm"):
        for module in ("caller", "provider"):
            run([sys.executable, str(ROOT / "exx"), "--platform", "z80", "--target", target,
                 "--abi", "shared.abi", f"{module}.exx", "-o", f"{module}.asm"], directory)
        if target == "asm":
            (directory / "bank.asm").write_text(
                f'    ORG {ORIGIN}\n    INCLUDE "caller.asm"\n    INCLUDE "provider.asm"\n')
            run([sjasmplus, "--nologo", "--raw=asm.bin", "bank.asm"], directory)
        else:
            run([z80asm, "caller.asm", "provider.asm"], directory)
            run([z80asm, "-b", f"-r={ORIGIN}", "-o=z80asm.bin", "caller.o", "provider.o"], directory)
        # Tail jump to $8003, followed by LD A,B and RET.
        if (directory / f"{target}.bin").read_bytes() != bytes.fromhex("c3 03 80 78 c9"):
            raise RuntimeError(f"{target}: incorrectly linked shared ABI example")
    print("shared ABI: separately compiled caller and provider linked to the expected 5 bytes")


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
                    example, "asm", args.sjasmplus, Path(scratch) / f"{example.stem}-sj",
                )
                linked = assemble(
                    example, "z80asm", args.z80asm, Path(scratch) / f"{example.stem}-z80asm",
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
                        f"(sjasmplus {len(binary)} bytes, z88dk-z80asm {len(linked)} bytes)"
                    )
                print(f"{example.name}: both assemblers produced the same {len(binary)} bytes")
            assemble_shared_abi(Path(scratch) / "shared", args.sjasmplus, args.z80asm)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
