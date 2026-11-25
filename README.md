# EXX

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
./exx --target sjasmplus examples/sdk_console_cursor.exx -o cursor.asm
./exx --target z88dk --section code_clib examples/sdk_console_cursor.exx -o cursor_z88dk.asm
z88dk-z80asm cursor_z88dk.asm
```

Use `INCLUDE "cursor.asm"` in the desired sjasmplus bank. The z88dk output
exports the procedure names with `PUBLIC` and imports the referenced external
procedures with `EXTERN`. Link the resulting object alongside ordinary ASM
objects. A C caller needs a compatible register convention or an ASM adapter.
Omit `-o` to print the generated assembly. The `--target` values select the
assembler dialect for the same Z80 instruction selection.

To regenerate assembly as part of an existing Make build:

```make
include path/to/exx/exx.mk
EXX_TARGET := sjasmplus

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

## Expressions and layouts

The first version supports `if`/`else`, `while`, calls, returns, byte loads,
register-pair immediates, accumulator arithmetic and XOR, and selected pair
operations. Expressions use explicit destinations. For `A = B + C`, write
`A = B` followed by `A += C`. Unsupported instruction forms produce a
source-line diagnostic. You can separate statements with newlines or semicolons.

In `context: VID_CTX → IY`, the type supplies the prefix for byte-field
offsets. `A = context->config` generates `ld a,(iy + VID_CTX.config)` for
sjasmplus. z88dk output uses `VID_CTX_config`. Supply the matching layout and
constants in the host assembly or with `--include layout.inc`. Uppercase
constant names and names such as `VID_CTX.slot0` are assembler symbols.
Numeric field offsets and bank addresses are the host assembler's responsibility.

The compiler tracks availability of physical locations. Conditional meanings
of results, such as “A holds an error only when CF is set”, belong to the
external ABI documentation in this version. The compiler trusts external ASM
declarations. Stack frames, register allocation and automatic saves are outside
the first version.

## Examples and verification

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

The assembly check requires sjasmplus and z88dk-z80asm on PATH. It assembles
and compares both outputs for every example. The DuoConf fixture supplies
layout constants and four external helper stubs at matching addresses. Use
`--sjasmplus PATH` or `--z80asm PATH` to select another installation.
