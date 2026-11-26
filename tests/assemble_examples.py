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
    constants = {
        "video_plan_plane": VIDEO_CONSTANTS,
        "bit_operations": {"PACKET.status": 0, "PACKET.flags": 1},
        "buffer": {"DRV_HEADER.ops": 6, "DUO_TSCONF": 1},
        "stack_arguments": {"DRAW_SURFACE.page0": 1},
        "structures": {"EXTERNAL_CELL.surface": 3},
    }.get(example.stem, {})
    helpers = VIDEO_HELPERS if example.stem == "video_plan_plane" else ()
    data = ("bs_storage_ops", "ts_storage_ops") if example.stem == "buffer" else ()
    command = [
        sys.executable, str(ROOT / "exx"), "--target", target,
        str(example), "-o", "generated.asm",
    ]
    if constants:
        if target != "z80asm":
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
    stub_code += "".join(f"{name}:\n    defb 0\n" for name in data)
    if target != "z80asm":
        wrapper = f'    ORG {ORIGIN}\n    INCLUDE "generated.asm"\n{stub_code}'
        (directory / "wrapper.asm").write_text(wrapper, encoding="ascii")
        run([assembler, "--nologo", "--raw=example.bin", "wrapper.asm"], directory)
    else:
        command = [assembler, "-b", f"-r={ORIGIN}", "-o=example.bin", "generated.asm"]
        if helpers or data:
            symbols = "".join(f"    PUBLIC {name}\n" for name in (*helpers, *data))
            (directory / "helpers.asm").write_text(
                f"    SECTION code_user\n{symbols}{stub_code}", encoding="ascii",
            )
            command.append("helpers.asm")
        run(command, directory)
    return (directory / "example.bin").read_bytes()


def assemble_branch_limits(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    source = directory / "branch_limit.exx"
    # Each indexed store is four bytes. Three INC HLs put the target at +127.
    for increments, branch in ((3, "30 7f"), (4, "d2 83 80")):
        body = "ptr[1] = 3\n" * 31 + "HL += 1\n" * increments
        source.write_text("skip(flag → CF, ptr → IX, p → HL) clobbers(HL) { if (flag) {\n"
                          + body + "}}\n", encoding="utf-8")
        expected = (bytes.fromhex(branch) + bytes.fromhex("dd 36 01 03") * 31
                    + bytes([0x23]) * increments + bytes([0xc9]))
        for target, tool in (("sjasmplus", sjasmplus), ("z80asm", z80asm)):
            if assemble(source, target, tool, directory / f"{target}-{increments}") != expected:
                raise RuntimeError(f"{target}: incorrectly encoded conditional branch over {124 + increments} bytes")
    print("forward branches: both assemblers produced JR at +127 and JP beyond it")


def assemble_long_repeat(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    source = directory / "long_repeat.exx"
    source.write_text("walk(p → HL, n → B) clobbers(HL, B) {repeat(n) {\n" +
                      "p += 1\n" * 130 + "}}\n", encoding="utf-8")
    # DJNZ skips the two-byte JR. On fallthrough JR skips the three-byte JP.
    expected = bytes([0x23]) * 130 + bytes.fromhex("10 02 18 03 c3 00 80 c9")
    for target, tool in (("sjasmplus", sjasmplus), ("z80asm", z80asm)):
        if assemble(source, target, tool, directory / target) != expected:
            raise RuntimeError(f"{target}: incorrect long repeat branch encoding")
    print("long repeat: both assemblers produced the expected back edge and exit")


def assemble_local_labels(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    source = directory / "local_labels.exx"
    source.write_text("""walk_first(count → B) clobbers(B) { repeat(count) {} }
walk_second(count → B) clobbers(B) { repeat(count) {} }
walk_raw(count → B) clobbers(B) {
    repeat(count) {
        asm {
raw_anchor:
    nop
        }
    }
}
""", encoding="utf-8")
    # Two short loops and a long back edge to walk_raw at $8006.
    expected = bytes.fromhex("10 fe c9 10 fe c9 00 10 02 18 03 c3 06 80 c9")
    for target, tool, prefix in (("sjasmplus", sjasmplus, "."), ("z80asm", z80asm, "@")):
        output = directory / target
        if assemble(source, target, tool, output) != expected:
            raise RuntimeError(f"{target}: local labels changed the branch destinations")
        listing = (output / "generated.asm").read_text(encoding="utf-8")
        if listing.count(f"\n{prefix}exx__1:\n") != 2 or "\nexx__walk_raw_1:\n" not in listing:
            raise RuntimeError(f"{target}: incorrect label spelling for EXX or mixed ASM procedures")
    print("local labels: both assemblers resolved repeated local names and branches across inline ASM")


def assemble_field_address(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    source = directory / "buffer.exx"
    source.write_text("extern data bs_storage_ops\nfield DRV_HEADER.ops: u16\n"
                      "install(h: DRV_HEADER → IY) { h->ops = &bs_storage_ops }\n", encoding="utf-8")
    # The external data starts at $8009 after the two indexed stores and RET.
    expected = bytes.fromhex("fd 36 06 09 fd 36 07 80 c9 00 00")
    for target, tool in (("asm", sjasmplus), ("z80asm", z80asm)):
        if assemble(source, target, tool, directory / target) != expected:
            raise RuntimeError(f"{target}: incorrectly linked address in u16 field")
    print("word field: both assemblers stored the expected relocated address")


def assemble_shared_abi(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    (directory / "shared.abi").write_text("extern A fetch(arg → B)\n")
    (directory / "provider.exx").write_text("A fetch(value → B) { return value }\n")
    (directory / "caller.exx").write_text("A forward(value → B) { return fetch(value) }\n")
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


def assemble_shared_structures(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    (directory / "layout.abi").write_text(
        "struct CELL { mode: u8, surface: SURFACE }\n"
        "struct SURFACE { page0: u8, page1: u8 }\n", encoding="utf-8")
    (directory / "provider.exx").write_text(
        "A provider(cell: CELL → IX) { return cell->surface.page1 }\n", encoding="utf-8")
    for target, assembler in (("sjasmplus", sjasmplus), ("z80asm", z80asm)):
        (directory / target).mkdir()
        module = directory / target
        cli = [sys.executable, str(ROOT / "exx"), "--target", target]
        run([*cli, "--layouts-only", "../layout.abi", "-o", "layout.inc"], module)
        run([*cli, "--abi", "../layout.abi", "../provider.exx", "-o", "provider.asm"], module)
        if target == "sjasmplus":
            assembly = (
                f'    ORG {ORIGIN}\n    INCLUDE "layout.inc"\n    INCLUDE "provider.asm"\n'
                "instance CELL\n    ld a,CELL.surface.page1\n    ld bc,CELL\n"
            )
            command = [assembler, "--nologo", "--raw=example.bin", "consumer.asm"]
        else:
            assembly = (
                '    SECTION code_user\n    INCLUDE "layout.inc"\n    INCLUDE "layout.inc"\n'
                "instance:\n    defs CELL,0\n    ld a,CELL_surface_page1\n    ld bc,CELL\n"
            )
            command = [assembler, "-b", f"-r={ORIGIN}", "-o=example.bin", "provider.asm", "consumer.asm"]
        (module / "consumer.asm").write_text(assembly, encoding="ascii")
        run(command, module)
        if (module / "example.bin").read_bytes() != bytes.fromhex("dd 7e 02 c9 00 00 00 3e 02 01 03 00"):
            raise RuntimeError(f"{target}: incorrect shared structure size or member offset")
    print("shared structures: both assemblers consumed generated layout includes")


def assemble_origin(directory: Path, sjasmplus: str, z80asm: str) -> None:
    directory.mkdir()
    (directory / "origin.exx").write_text(
        "const { START = 0x8123, VALUE = 9 }\norigin START\ndata marker: u8 = VALUE\n"
        "HL address() { return &marker }\n", encoding="utf-8")
    for target, assembler in (("sjasmplus", sjasmplus), ("z80asm", z80asm)):
        run([sys.executable, str(ROOT / "exx"), "--target", target, "origin.exx",
             "-o", "generated.asm"], directory)
        command = ([assembler, "--nologo", "--raw=example.bin", "generated.asm"] if target == "sjasmplus"
                   else [assembler, "-b", "-o=example.bin", "generated.asm"])
        run(command, directory)
        binary = "example.bin" if target == "sjasmplus" else "example_code_user.bin"
        if (directory / binary).read_bytes() != bytes.fromhex("09 21 23 81 c9"):
            raise RuntimeError(f"{target}: origin did not place the data at 0x8123")
    print("origin and constants: both assemblers resolved the same bytes and address")


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
            assemble_shared_structures(Path(scratch) / "structures-shared", args.sjasmplus, args.z80asm)
            assemble_origin(Path(scratch) / "origin", args.sjasmplus, args.z80asm)
            assemble_branch_limits(Path(scratch) / "branches", args.sjasmplus, args.z80asm)
            assemble_long_repeat(Path(scratch) / "long", args.sjasmplus, args.z80asm)
            assemble_local_labels(Path(scratch) / "labels", args.sjasmplus, args.z80asm)
            assemble_field_address(Path(scratch) / "word", args.sjasmplus, args.z80asm)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
