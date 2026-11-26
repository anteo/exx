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

## Arithmetic and bits

### Integer literals

Use decimal, hexadecimal or binary notation. Both assignments below load 128.

```text
A = 0x80
B = 0b10000000
```

```asm
    ld a, 128
    ld b, 128
```

### Accumulator arithmetic

Choose the destination explicitly. To add B and C, copy B into A and add C. Separate statements
with newlines or semicolons. Unsupported forms produce a diagnostic on the source line.

```text
A = B
A += C
```

```asm
    ld a, b
    add a, c
```

### Register-pair arithmetic

Increment or decrement a cursor directly. `HL += DE` selects `add hl,de`.

```text
HL += DE
HL -= 1
```

```asm
    add hl, de
    dec hl
```

### Bit tests

`$` selects a constant bit index from 0 to 7. Testing a register or indexed field uses `bit` and
preserves CF.

```text
if (packet->status$3) return 1
return 0
```

```asm
    bit 3, (iy + PACKET.status)
    jp z, exx__example_1
    ld a, 1
    ret
exx__example_1:
    ld a, 0
    ret
```

### Bit writes

Assign `true` or `false` to select `set` or `res`. Both instructions preserve F.

```text
packet->status$3 = false
```

```asm
    res 3, (iy + PACKET.status)
```

### AND masks

Keep selected bits in A with `&=`. This constant mask emits `and 127` and updates F.

```text
A &= ~(1 << 7)
```

```asm
    and 127
```

### OR masks

Set the mask bits in A with `|=`. This emits `or 128` and updates F.

```text
A |= 0x80
```

```asm
    or 128
```

### Exclusive OR

Toggle bits with `^=`. A register operand selects `xor` and updates F.

```text
A ^= E
```

```asm
    xor e
```

### Byte complement

`~A` inverts all eight bits using `cpl`. CF, S, Z and PV are preserved.

```text
A = ~A
```

```asm
    cpl
```

### Logical byte shifts

`<<=` shifts left and `>>=` shifts right, filling with zeros. Byte shifts and rotations accept a
byte register or indexed byte field and a count known to EXX (0–255). Each step updates F. Zero
steps preserve the value and flags.

```text
B >>= 2
```

```asm
    srl b
    srl b
```

### Arithmetic right shift

`sra` copies the sign bit into the high bit at each step. Named shifts and
rotations default to one step.

```text
sra(D, 2)
```

```asm
    sra d
    sra d
```

### Word left shift

Shifting HL left by one selects `add hl,hl`. It updates CF, HF and N and preserves the remaining
documented flags.

```text
HL <<= 1
```

```asm
    add hl, hl
```

### Circular rotations

`rlc` rotates left and `rrc` rotates right. The outgoing bit wraps around to the
other end of the byte and is also copied to CF.

```text
rlc(B)
```

```asm
    rlc b
```

### Rotations through carry

`rl` and `rr` use CF as an extra bit. Here `sra d` puts bit 0 of
D in carry, then `rr e` shifts that bit into E.

```text
sra(D)
rr(E)
```

```asm
    sra d
    rr e
```

### Addition with carry

`adc` adds the second operand and incoming CF to the first operand and updates F. Both A
and HL have Z80 forms.

```text
adc(HL, DE)
```

```asm
    adc hl, de
```

### Subtraction with borrow

`sbc` subtracts the second operand and incoming CF from the first and updates F. Here it
selects `sbc a,e`.

```text
sbc(A, E)
```

```asm
    sbc a, e
```

### Counted loops

`repeat` runs the body, then decrements B using `djnz`, preserving flags for the loop test. An
initial zero gives 256 iterations if the body leaves B alone. For a potentially out-of-range
back edge EXX uses a nearby `djnz` and absolute jumps.

```text
count → B
count = 16
repeat (count) {
    *HL = A
    HL += 1
}
```

```asm
    ld b, 16
exx__example_1:
    ld (hl), a
    inc hl
    djnz exx__example_1
```

### Early loop exit

`break` exits the innermost `while` or `repeat`. Here a zero byte exits before either HL or B changes.

```text
repeat (B) {
    if (!(A = *HL)) break
    HL += 1
}
```

```asm
exx__example_1:
    ld a, (hl)
    or a
    jp z, exx__example_2
    inc hl
    djnz exx__example_1
exx__example_2:
```

## Memory and symbols

### Byte pointers

`*ptr` accesses the byte addressed by BC, DE, HL, IX or IY. Transfers through BC and DE require
A. This copy emits `ld a,(de)` followed by `ld (hl),a`.

```text
(src, dst) → (DE, HL)
A = *src
*dst = A
```

```asm
    ld a, (de)
    ld (hl), a
```

### Indexed bytes

An IX or IY pointer accepts a constant displacement from −128 to 127. The host assembler
resolves symbolic offsets.

```text
previous(cursor → IX) → A { return cursor[-1] }
```

```asm
previous:
    ld a, (ix - 1)
    ret
```

### Typed structure fields

A layout name supplies the offset prefix and is checked even when the pointer is passed by
register or alias. A byte load below uses `VID_CTX.config` for `asm` and `VID_CTX_config` for
`z80asm`. The caller supplies the actual address.

```text
config(ctx: VID_CTX → IY) → A { return ctx->config }
```

```asm
config:
    ld a, (iy + VID_CTX.config)
    ret
```

### Word fields

Fields default to `u8`. Declare `u16` to read or write two bytes, low byte first. Both offsets
must fit the index range. BC, DE and HL can hold the word. Stores also accept constants.

```text
field DRV_HEADER.ops: u16
install(h: DRV_HEADER → IY, table → HL) { h->ops = table }
```

```asm
install:
    ld (iy + DRV_HEADER.ops), l
    ld (iy + DRV_HEADER.ops + 1), h
    ret
```

### External data addresses

Declare an assembly data symbol with `extern data` and take its address with `&`. The `z80asm`
target emits `EXTERN` for referenced data.

```text
extern data bs_storage_ops
table_address() → HL { return &bs_storage_ops }
```

```asm
table_address:
    ld hl, bs_storage_ops
    ret
```

### Assembler constants

Uppercase names and qualified offsets remain symbolic. The host assembler supplies their values
and bank addresses.

```text
A = VID_CTX.slot0 ^ VID_CTX.slot1
```

```asm
    ld a, 0 + (VID_CTX.slot0 ^ VID_CTX.slot1)
```

## Stack and register banks

### Scoped register saves

`keep` pushes register pairs in list order and pops them in reverse order. Aliases are valid here.
This copy preserves both pointers, the count and AF, using eight bytes of stack.

```text
copy_bytes(source → HL, destination → DE, count → BC) {
    keep(AF, source, destination, count) {
        ldir(destination, source, count)
    }
}
```

```asm
copy_bytes:
    push af
    push hl
    push de
    push bc
    ldir
    pop bc
    pop de
    pop hl
    pop af
    ret
```

Nested blocks restore from the inside out. An early `return` restores all active saves. A `break`
restores only the blocks it leaves. Conditions use the flags at the branch, before restoration.
EXX reports an error if it cannot prove that restoring a pair preserves a live result or a tail-call
argument. For example, when returning A, place `return 5` after `keep(AF)` to return the new value.
Manual pushes and pops inside the block must balance above its saved words.

### Stack saves

`push` saves a word and `pop` restores it into the chosen pair. EXX tracks which parts were
initialized across calls. A restored BC can be preserved by the caller’s ABI. Stack depth must
match at joins and return to its entry value at every exit, including tail calls. SP is reserved
for the call stack. Keep saved words intact when writing through pointers.

```text
extern work() clobbers(BC)
run_preserving_bc() {
    push(BC)
    work()
    pop(BC)
}
```

```asm
run_preserving_bc:
    push bc
    call work
    pop bc
    ret
```

### Register-pair exchange

Exchange DE and HL in one instruction. Both `ex(DE, HL)` and `ex(HL, DE)` emit the same code.

```text
ex(DE, HL)
```

```asm
    ex de, hl
```

### Exchange with the stack

`ex_sp` exchanges HL, IX or IY with a saved word. Here IX receives the previous BC, then DE
receives the previous IX.

```text
push(BC)
ex_sp(IX)
pop(DE)
```

```asm
    push bc
    ex (sp), ix
    pop de
```

### Shadow registers

`ex(AF)` selects `ex af,af'`. Use `exx()` to exchange BC, DE and HL with their shadow pairs together.
Signatures can name `AF_ALT`, `BC_ALT`, `DE_ALT` and `HL_ALT`. The example writes the alternate
HL and restores the active bank.

```text
set_alt_pointer(pointer → HL) clobbers(HL_ALT) {
    push(pointer)
    exx()
    pop(HL)
    exx()
}
```

```asm
set_alt_pointer:
    push hl
    exx
    pop hl
    exx
    ret
```

## Ports and block operations

### Port input

With BC, `in` uses the full port address, updates flags and preserves CF. In the immediate
form, `A = in(0xFE)`, incoming A supplies the high address byte and F is preserved.

```text
D = in(BC)
```

```asm
    in d, (c)
```

### Port output

`out(BC, E)` outputs E at the full BC address. In the immediate form shown here, A supplies
both the high address byte and the value written. Both forms preserve F.

```text
out(0xFE, A)
```

```asm
    out (254), a
```

### Block copy

`ldir()` copies from HL to DE with BC as the count. An initial zero copies 65,536 bytes.
Use `ldi`, `ldir`, `ldd` or `lddr` to choose direction and repetition.
Every block operation accepts either empty parentheses or its full register list. Both forms
read and modify the same registers and flags. The explicit form checks aliases in order:
with the bindings below, `ldir(src, dst, count)` is a compile-time error.

```text
(dst, src, count) → (DE, HL, BC)
ldir(dst, src, count)
```

```asm
    ldir
```

### Block search

`cpir()` compares A with bytes starting at HL until it finds a match or exhausts BC.
The search family includes `cpi`, `cpir`, `cpd` and `cpdr`.

```text
cpir(HL, A, BC)
```

```asm
    cpir
```

### Block input

`inir()` fills memory starting at HL. C supplies the low port byte. B counts transfers and
supplies the high port byte. The input family includes `ini`, `inir`, `ind` and `indr`.
After block I/O the analyzer exposes Z and treats the
remaining flags as clobbered.

```text
inir(HL, C, B)
```

```asm
    inir
```

### Block output

`otir()` sends bytes starting at HL to the port, advancing HL and decrementing B at each
transfer. The output family includes `outi`, `otir`, `outd` and `otdr`.

```text
otir(C, HL, B)
```

```asm
    otir
```
