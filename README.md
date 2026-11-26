# EXX

[![English](https://img.shields.io/badge/lang-en-blue.svg)](README.md) [![Русский](https://img.shields.io/badge/lang-ru-green.svg)](README.ru.md)

EXX translates high-level assembly into symbolic Z80 assembly.
Procedures declare their input registers, results and clobbers.
EXX requires Python 3.10 or newer and uses only the standard library.

[Syntax manual](MANUAL.md)

## Example

Return the smaller of two unsigned bytes. The inputs arrive in A and B,
the result returns in A, and the comparison changes the flags in F.

```text
minimum(value → A, limit → B) → A clobbers(F) {
    if (value < limit) return value
    return limit
}
```

```asm
minimum:
    cp b
    ret c
    ld a, b
    ret
```

## Build a module

### Assembly fragment

The `asm` target emits a plain Z80 assembly fragment for inclusion in an
assembly project. The surrounding source determines its address. The examples
are tested with sjasmplus, which includes the fragment with `INCLUDE "cursor.asm"`.

```sh
./exx --target asm examples/sdk_console_cursor.exx -o cursor.asm
```

The two cursor routines can now be included together. [Generated cursor.asm](tests/golden/asm/sdk_console_cursor.asm)

### Linkable assembly module

The `z80asm` target emits the same instructions with `SECTION`, `PUBLIC` and `EXTERN` for
`z88dk-z80asm`. Link the object with other ASM modules. A C caller needs a compatible calling
convention or an ASM adapter.

```sh
./exx --target z80asm --section code_clib examples/sdk_console_cursor.exx -o cursor.asm
z88dk-z80asm cursor.asm
```

The generated module begins with these directives.

```asm
    SECTION code_clib
    PUBLIC zx__console_newline
    PUBLIC zx__console_advance
```

### CPU selection

Use `--platform` to select the CPU. By default EXX uses the first platform supported by the
target. Omitting `-o` prints the assembly to stdout.

```sh
./exx --platform z80 --target asm examples/advance_block.exx
```

The output contains both the routine and its caller. [Generated advance_block.asm](tests/golden/asm/advance_block.asm)

### Assembler includes

Use `--include` to place layout and constant definitions before the generated procedures.

```sh
./exx --target asm --include layout.inc examples/buffer.exx -o buffer.asm
```

```asm
    INCLUDE "layout.inc"
```

### Shared interfaces

Pass the same declarations to the caller and the implementation. EXX checks input registers and
layouts, result order and clobbers. Repeat `--abi` to load several interfaces. External ASM
implementations must honour their declarations.

```sh
./exx --target z80asm --abi video.abi video.exx -o video.asm
./exx --target z80asm --abi video.abi caller.exx -o caller.asm
```

For example, put `extern read_page(page → E) → A` in `video.abi`. With
`read_page(page → E) → A { return page }` in `video.exx` and
`fetch_page(page → E) → A { return read_page(page) }` in `caller.exx`, the two modules use the same symbol.

```asm
; video.asm
    SECTION code_user
    PUBLIC read_page

read_page:
    ld a, e
    ret
```

```asm
; caller.asm
    SECTION code_user
    PUBLIC fetch_page
    EXTERN read_page

fetch_page:
    jp read_page
```

### Make integration

Include `exx.mk` to rebuild the assembly when the source, compiler or a shared file listed in
`EXX_ABI` changes.

```make
include path/to/exx/exx.mk
EXX_TARGET := asm
EXX_ABI := video.abi

build/%.asm: src/%.exx $(EXX_TOOL_DEPS)
	$(exx_compile)
```

## Editor highlighting

Zed and VS Code recognize `.exx` files and highlight EXX syntax and embedded
Z80 assembly using the active theme. Run `make install` from the repository
root to build and install the extensions for editors it finds. The installer
prints a message for each missing editor and returns an error if a build or
installation fails. It looks for `zed`, `zeditor`, and `code` on `PATH` and
also checks the system and user Applications folders on macOS.

- **Zed.** `make zed-install` registers `build/zed/exx` as a local dev extension.
  Keep that directory while the extension is installed. Restart Zed if it was
  open. To install through the editor, run `make zed` and
  select `build/zed/exx` with **Install Dev Extension**. Building requires
  Node.js and the [Tree-sitter CLI](https://tree-sitter.github.io/tree-sitter/cli/).
  The first build may download the WASI SDK for Tree-sitter.
- **VS Code.** `make vscode-install` uses the VS Code CLI. Set `CODE` to use a
  specific executable. Building requires Node.js 20 or later and npm. For
  installation through the editor, run `make vscode` and select `build/exx.vsix`
  with **Extensions: Install from VSIX**.

`make editors` builds both extensions and also builds Quick Look on macOS.

## Quick Look on macOS

The Quick Look extension previews `.exx` files in Finder with highlighting
for keywords, Z80 registers, flags, numbers, strings and comments.
Build and install it from the repository root with the macOS developer tools.

```sh
make quicklook-install
```

The installer registers the extension in `~/Applications/EXX File Type.app`.
Select an EXX file in Finder and press Space.
To build the app separately, run `make quicklook`. The signed app is in
`build/quicklook/`.

## Automatic branch selection

For both `asm` and `z80asm`, EXX emits `jr` for unconditional jumps and for
`Z`, `NZ`, `C`, or `NC` when the destination is −128 to +127 bytes from the
end of the instruction. This also applies to a tail jump to another procedure
in the same module. Other conditions, external destinations, and jumps across
a raw assembly block use `jp`. Instructions written inside `asm` pass through verbatim.

[Conditional branch example](MANUAL.md#conditional-branching)

## Complete examples

- [inline_asm.exx](examples/inline_asm.exx) — hexadecimal lookup table and inline assembly with register effects. [asm](tests/golden/asm/inline_asm.asm) · [z80asm](tests/golden/z80asm/inline_asm.asm)
- [buffer.exx](examples/buffer.exx) — symbol addresses, word fields and bounded buffer copying. [asm](tests/golden/asm/buffer.asm) · [z80asm](tests/golden/z80asm/buffer.asm)
- [transfer.exx](examples/transfer.exx) — stack saves, shadow registers and port access. [asm](tests/golden/asm/transfer.asm) · [z80asm](tests/golden/z80asm/transfer.asm)
- [bit_operations.exx](examples/bit_operations.exx) — indexed bits and a signed shift across two registers. [asm](tests/golden/asm/bit_operations.asm) · [z80asm](tests/golden/z80asm/bit_operations.asm)
- [video_plan_plane.exx](examples/video_plan_plane.exx) — DuoConf plane selection with external calls and flag results. [asm](tests/golden/asm/video_plan_plane.asm) · [z80asm](tests/golden/z80asm/video_plan_plane.asm)
- [sdk_console_cursor.exx](examples/sdk_console_cursor.exx) — the two zxevo-sdk cursor routines with their BC/DE ABI. [asm](tests/golden/asm/sdk_console_cursor.asm) · [z80asm](tests/golden/z80asm/sdk_console_cursor.asm)
- [advance_block.exx](examples/advance_block.exx) — loop with three results in A, HL and DE. [asm](tests/golden/asm/advance_block.asm) · [z80asm](tests/golden/z80asm/advance_block.asm)

## Language comparison

| Language | Strengths and typical uses | Limitations |
| --- | --- | --- |
| **EXX** | Register names and flags are part of the interface. A driver can return a status in CF alongside a byte in A, and `keep(BC)` can preserve a caller’s counter across several exits. EXX checks these contracts across branches and calls. | You choose working registers and write the moves. Even a byte comparison between C and D needs an explicit accumulator load. Algorithms with many intermediate values require more bookkeeping. |
| **Wiz** | Structures, arrays, pointers and individual bits make hardware data layouts readable. A field such as `monster.flags$0` names a bit directly. Banks and compile-time expressions are useful for game data and memory maps. | Expression selection depends on the target CPU’s registers and addressing modes. An expression with no instruction match must be split into supported steps. Moving hardware-specific code to another Wiz target can require rewriting it. [Wiz language guide](https://github.com/wiz-lang/wiz) · [Z80 bit-field examples](https://github.com/wiz-lang/wiz/blob/5a8ea1ce15953d6ed9d222a54a31cb6447c79121/tests/block/z80_bitindex_i8.wiz) |
| **Z80HLA** | Structured loops and branches fit hand-written instruction sequences. A loop can end with `dec a` followed by `while(nz)`, using the flag that the decrement just set. Structures and unions give names to data layouts. | The programmer selects loads, temporaries and arithmetic instructions. A `function` declaration has an empty parameter list, so callers must track the argument registers and flag results by convention. [Z80HLA manual](https://github.com/internalregister/z80hla/blob/master/MANUAL.md) |
| **C with SDCC** | Locals, pointers, arrays and compound expressions suit parsers, state machines and buffer algorithms. The optimizer allocates registers, so adding an intermediate value rarely requires reorganizing the whole routine. | The generated instruction sequence depends on optimization. For a loop with a fixed cycle budget, inspect the generated ASM. A hardware flag used as an extra return value can require an assembly wrapper. [SDCC manual](https://sdcc.sourceforge.net/doc/sdccman.pdf) |

### Build integration

| Tool | Output and integration |
| --- | --- |
| **EXX** | Include the generated `asm` in the host assembler, or assemble the `z80asm` output with `z88dk-z80asm` and link the object. [Build a module](#build-a-module) |
| **Wiz** | Wiz lays out banks and writes a raw binary or a supported console ROM image. When embedding a separately built binary, the host project must agree on placement and external addresses. [Wiz output formats](https://github.com/wiz-lang/wiz#features) |
| **Z80HLA** | The assembler reads one entry file, follows its includes and writes a binary. An instruction listing is optional. [Z80HLA command-line options](https://github.com/internalregister/z80hla#using-it) |
| **SDCC** | Use `sdcc -mz80 -c` to build a relocatable object for a compatible linker, or `sdcc -mz80 -S` to inspect the assembly. Mixed C and ASM modules must agree on the calling convention. [SDCC manual](https://sdcc.sourceforge.net/doc/sdccman.pdf) |

## Compiler development

### CPU platform registration

The tokenizer and parser in `exxlang/tokenizer.py` and `exxlang/parser.py` build nodes from
`exxlang/syntax.py`. A registered platform defines register overlap, selects instructions and
records their effects. Branches describe their destination and fallthrough for the shared flow
analysis. The Z80 implementation starts with this declaration.
[Z80 platform](exxlang/platforms/z80.py)

```python
@platforms.register
class Z80:
    name = "z80"
    ...
```

### Assembler target registration

A target declares its supported platforms and can override the assembly header and operand
spelling. The registries discover modules in `exxlang/platforms/` and `exxlang/targets/`. The
CLI uses the registered names to check the selected combination.
[Plain ASM target](exxlang/targets/asm.py)

```python
@targets.register
class PlainAsm(Assembler):
    name = "asm"
    platforms = ("z80",)
```

### Assembly text regression tests

The unit suite runs each `examples/*.exx` through the CLI and compares its complete output to
`tests/golden/asm/` and `tests/golden/z80asm/`. A mismatch shows the changed lines. Review the
reference files when changing the output intentionally. Tokenizer, parser and register contracts
have dedicated tests. CPU-specific tests live in `tests/platforms/`.

```sh
make test
```

### Binary comparison

The assembly check compares both binaries for every example. The DuoConf fixture supplies
matching layout constants and four external helper stubs at the same addresses. Put sjasmplus
and z88dk-z80asm on PATH or set `SJASMPLUS` and `Z88DK_Z80ASM` to their paths.

```sh
make test-asm
```
