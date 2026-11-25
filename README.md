# EXX

[![English](https://img.shields.io/badge/lang-en-blue.svg)](README.md) [![Русский](https://img.shields.io/badge/lang-ru-green.svg)](README.ru.md)

EXX translates high-level assembly procedures into symbolic Z80 assembly. Each
procedure declares its register ABI. You can replace a routine in a ROM bank
or compile an object for a z88dk library while keeping its existing callers.
The compiler runs with Python 3.10 or newer and uses only the standard library.

```text
extern video_stack_safe(window → B, session: VID_SESSION → IX)
    → (CF, A) clobbers(C, HL, F)

check_window(window → B, session: VID_SESSION → IX)
    → (CF, A) clobbers(C, HL, F) {
    (CF, A) = video_stack_safe(window, session)
    if (CF) return (CF, A)
    return (0, 1)
}
```

The arguments already occupy B and IX. The call and the error check compile to
`call video_stack_safe` and `ret c`. The success return uses `xor a`,
`inc a`, `ret`, yielding A=1 and a clear carry.

## Compile a module

```sh
./exx --target asm examples/sdk_console_cursor.exx -o cursor.asm
./exx --target z80asm --section code_clib examples/sdk_console_cursor.exx -o cursor_z80asm.asm
z88dk-z80asm cursor_z80asm.asm
```

The `asm` target emits an assembly fragment with labels, instructions and any
requested includes. Its host supplies symbol definitions, including dotted
layout offsets, and chooses where to place the code. In a sjasmplus bank use
`INCLUDE "cursor.asm"`. The `z80asm` target emits a module for `z88dk-z80asm`. It
exports the procedure names with `PUBLIC` and imports the referenced external
procedures with `EXTERN`. Link the resulting object alongside ordinary ASM
objects. A C caller needs a compatible register convention or an ASM adapter.
Omit `-o` to print the generated assembly. Both targets render the same
selected Z80 instructions. Use `--platform z80` to select the CPU explicitly.
With just `--target`, the target selects its first supported platform.

For separately compiled procedures, put their shared `extern` declarations
in a file and pass it to each compilation. EXX checks the implementation
against the declared input locations and layouts, ordered outputs and clobbers.
The caller obtains its declarations from the same file. For example:

```sh
./exx --target z80asm --abi video.abi video.exx -o video.asm
./exx --target z80asm --abi video.abi caller.exx -o caller.asm
```

You can repeat `--abi` to import several interfaces. Assembly routines
described by an interface must implement the declared contract.

To regenerate assembly as part of an existing Make build:

```make
include path/to/exx/exx.mk
EXX_TARGET := asm
# For modules sharing external contracts:
# EXX_ABI := video.abi

build/%.asm: src/%.exx $(EXX_TOOL_DEPS)
	$(exx_compile)
```

## Register contracts

- Bind parameters with `window → B` or declare local names with
  `(window, page) → (B, E)`. A binding names the current contents of the
  physical register. Assignments perform the actual moves.
- Calls check argument count and location. If the next procedure takes its
  argument in E and the value is in D, write `E = D` before the call.
- Results may occupy multiple independent locations, e.g. `→ (A, HL, DE)`.
  Capture them in signature order or call the procedure as a statement.
  `return (status, cursor, remaining)` places the values in their declared
  locations. A register permutation that needs temporary storage requires
  explicit moves. `return helper(args)` tail-jumps to a routine with a matching
  result ABI. External routines must be reachable in the active memory map.
- `clobbers(C, HL, F)` allows the callee to overwrite those resources.
  After the call, a declared output takes precedence over a clobber of the
  same location. Reads require initialization on every incoming path, including
  loop back edges. BC, DE, HL and AF overlap their components. F covers the
  six documented status flags. SP is reserved for the call stack.
- `if (CF)` and `if (Z)` read the current flags. `if (A)` and `if (!A)`
  test the accumulator via `or a`, which writes F. Declare the changed
  resources as outputs or clobbers. Comparisons are unsigned. A comparison of
  two bytes needs A as one of its operands. `&&` and `||` short-circuit.
- A parenthesized assignment can supply a condition operand in `if` or
  `while`. For example, `if ((A = session->action) == RST8_VID_PREP_DRAW)`
  loads A once and then compares it. In `if (Z && (A = session->action) == 1)`,
  the load runs only when Z was set. A keeps its resulting value on each path.
  An alias bound to A can appear in its place.

## Expressions and layouts

EXX supports `if`/`else`, `while`, calls, returns, byte loads,
register-pair immediates, accumulator arithmetic and XOR, and selected pair
operations. Expressions use explicit destinations. For `A = B + C`, write
`A = B` followed by `A += C`. Unsupported instruction forms produce a
source-line diagnostic. You can separate statements with newlines or semicolons.

In `context: VID_CTX → IY`, the type supplies the prefix for byte-field
offsets. `A = context->config` generates `ld a,(iy + VID_CTX.config)` for
sjasmplus. The `z80asm` target uses `VID_CTX_config`. Supply the matching layout and
constants in the host assembly or with `--include layout.inc`. Uppercase
constant names and names such as `VID_CTX.slot0` are assembler symbols.
Numeric field offsets and bank addresses are the host assembler's responsibility.
Passing IY directly or through a local alias uses the layout declared for IY
in the calling procedure. This checks the nominal interface. The caller is
responsible for the address held in the register.

The compiler checks which registers and flags are available on each path.
Document any conditions on their meaning in the procedure's ABI, such as
“A holds an error code when CF is set.” For external ASM procedures, EXX
relies on the declared contract. The programmer chooses the registers and
handles any stack frames and register saves.

## Examples and verification

The frontend lives in `exxlang/tokenizer.py` and `exxlang/parser.py`.
The parser builds the nodes in `exxlang/syntax.py`. Processor-specific
instruction selection lives in `exxlang/platforms/z80.py`. Each platform
registers its class with `@platforms.register` and owns the register model,
instruction selection and instruction effects. Conditional transfers describe
their destination and fallthrough explicitly for the shared flow analysis.
Each assembler target in `exxlang/targets/` registers with `@targets.register`
and declares its supported platform names. A target can inherit the common
assembly printer and override its header and operand spelling.
The registries discover modules in their respective packages. The CLI builds
its choices from registered names and checks the selected combination.
The tokenizer,
parser and register contracts have separate unit tests. CPU-specific tests
live under `tests/platforms/`.

- [video_plan_plane.exx](examples/video_plan_plane.exx) implements the DuoConf
  plane planner with indexed fields, external procedures, and flag returns.
- [sdk_console_cursor.exx](examples/sdk_console_cursor.exx) implements the two
  zxevo-sdk cursor routines with their BC/DE ABI.
- [advance_block.exx](examples/advance_block.exx) shows a loop and a three-value
  result in A, HL and DE.

```sh
python3 -m unittest discover -s tests
python3 tests/assemble_examples.py
```

The unit suite compiles each `examples/*.exx` through the CLI and compares the
full output with `tests/golden/asm/<name>.asm` and `tests/golden/z80asm/<name>.asm`.
A mismatch shows a line-by-line diff. When changing the generated assembly
intentionally, review and update the affected reference files.

The assembly check requires sjasmplus and z88dk-z80asm on PATH. It assembles
and compares both outputs for every example. The DuoConf fixture supplies
layout constants and four external helper stubs at matching addresses. Use
`--sjasmplus PATH` or `--z80asm PATH` to select another installation.
