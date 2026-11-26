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

```asm
check_window:
    call video_stack_safe
    ret c
    xor a
    inc a
    ret
```

The arguments already occupy B and IX. The call and the error check compile to
`call video_stack_safe` and `ret c`. The success return uses `xor a`,
`inc a`, `ret`, yielding A=1 and a clear carry.

## Reading the examples

Each EXX example is followed by output from the `asm` target unless another target is named.
For procedure-body fragments, the listing shows the corresponding instructions and branch
labels. The enclosing procedure’s entry label and implicit final `ret` are omitted.
In these fragments `session` is a `VID_SESSION` pointer in IX and `packet` is a `PACKET` pointer in IY.

## Build a module

### Assembly fragment

The `asm` target emits symbolic Z80 instructions. Include the file in the desired ROM bank with
`INCLUDE "cursor.asm"`. The host assembler determines its address.

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

### File-scope assembly

Use `asm { … }` to place tables, labels, macros or assembler directives between EXX procedures.
Both targets emit the body in source order after the generated module header. Indentation, symbol
spelling and comments inside the body pass through to the selected assembler. Write conditional
assembly in its native dialect. EXX provides no separate `#define` or `#ifdef` preprocessor.

```text
asm {
hex_digits:
    defb "0123456789ABCDEF"
}
```

```asm
hex_digits:
    defb "0123456789ABCDEF"
```

### Inline assembly with a register contract

Inside a procedure, write the registers read in parentheses, the results after the arrow and
other modified registers in `clobbers`. A contract can use register aliases. Inside the
assembler text use the physical names. An omitted list is empty, so `asm { nop }` preserves
all registers and flags. EXX uses the declaration to check surrounding code. The author of the
block must honour it, preserve stack balance and pass control to the following EXX statement.
Declare external references used solely in raw assembly using the assembler’s directives.

```text
invert(value → A) → A clobbers(HF, N) {
    asm(value) → A clobbers(HF, N) {
        cpl
    }
    return value
}
```

```asm
invert:
        cpl
    ret
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

## Procedures and registers

### Source comments

Both targets copy `//` and `/* … */` comments into the assembly as semicolon-prefixed lines.
Procedure descriptions appear above their labels. A comment on a statement that emits no
code stays in source order alongside the remaining instructions.

```text
// Return the page number supplied by the caller.
read_page(page → E) → A {
    /* The caller expects the result in A. */
    return page
}
```

```asm
; Return the page number supplied by the caller.
read_page:
    ; The caller expects the result in A.
    ld a, e
    ret
```

### Register parameters

An arrow binds a parameter name to the register that holds it on entry. Here `page` already occupies E.

```text
read_page(page → E) → A { return page }
```

```asm
read_page:
    ld a, e
    ret
```

### Local register aliases

A local binding gives one register or a tuple of registers a name. Reading an alias reads the
register’s current value.

```text
(cursor, remaining) → (HL, DE)
cursor += 1
```

```asm
    inc hl
```

### Checked calls

EXX checks the number and location of arguments. This caller explicitly moves D into the
required register E.

```text
extern select_page(page → E)
select_from_d(page → D) clobbers(E) {
    E = page
    select_page(E)
}
```

```asm
select_from_d:
    ld e, d
    call select_page
    ret
```

### Multiple return values

Return values in signature order. Here CF keeps its current value and A receives 5. A
permutation that needs a temporary register requires explicit moves.

```text
status(carry → CF) → (CF, A) { return (carry, 5) }
```

```asm
status:
    ld a, 5
    ret
```

### Capturing call results

List all result locations in declaration order. A standalone call discards the results. Document
conditional meanings such as an error code in A when CF is set.

```text
extern query() → (A, HL, DE)
inspect() → HL clobbers(A, DE) {
    (A, HL, DE) = query()
    return HL
}
```

```asm
inspect:
    call query
    ret
```

### Tail calls

Returning a call with a matching result ABI generates a jump. The destination must be reachable
in the active memory map.

```text
extern read_byte() → A
fetch() → A { return read_byte() }
```

```asm
fetch:
    jp read_byte
```

### Clobber declarations

`clobbers` permits changes visible to the caller. A result remains available even if its
register also appears in `clobbers`. F covers the six documented flags. AF, BC, DE and HL
overlap their components.

```text
extern probe() → (CF, A) clobbers(HL, F)
```

An `extern` declaration emits no instructions. Calling `probe` from a `z80asm` module adds `EXTERN probe` to its header.

### Definite assignment

A read requires a value on every incoming path, including loop back edges. After `work()` the
caller must initialize D before returning DE.

```text
extern work() clobbers(D)
reset_high(word → DE) → DE {
    work()
    D = 0
    return word
}
```

```asm
reset_high:
    call work
    ld d, 0
    ret
```

## Conditions and loops

### Flag tests

`if (CF)` and `if (Z)` read the current flag. Immediately after a call this tests the flag
supplied by the callee.

```text
(CF, A) = probe()
if (CF) return (CF, A)
return (0, 1)
```

```asm
    call probe
    ret c
    xor a
    inc a
    ret
```

### Accumulator tests

`if (A)` tests for a nonzero byte and `if (!A)` tests for zero. Both emit `or a`, which updates F.

```text
if (!A) return A
return 1
```

```asm
    or a
    ret z
    ld a, 1
    ret
```

### Unsigned comparisons

Compare bytes with A as one operand. `else` selects the other branch. The comparison updates flags.

```text
if (A < C) return A
else return C
```

```asm
    cp c
    ret c
    ld a, c
    ret
```

### Assignment in a condition

Parenthesize the assignment to load a register exactly where its value is tested. The
destination may be a register alias.

```text
if ((A = session->action) == RST8_VID_PREP_DRAW) return 1
return 0
```

```asm
    ld a, (ix + VID_SESSION.action)
    cp RST8_VID_PREP_DRAW
    jr nz, exx__example_1
    ld a, 1
    ret
exx__example_1:
    ld a, 0
    ret
```

### Short-circuit conditions

`&&` and `||` evaluate the right operand only when needed. Here A receives the field value only
on the path where Z is set.

```text
if (Z && (A = session->action) == 1) return A
return 0
```

```asm
    jr nz, exx__example_1
    ld a, (ix + VID_SESSION.action)
    cp 1
    ret z
exx__example_1:
    ld a, 0
    ret
```

### Pre-test loops

`while` tests before each iteration. A zero in A skips this loop entirely.

```text
while (A) {
    HL += 1
    A -= 1
}
```

```asm
exx__example_1:
    or a
    jr z, exx__example_2
    inc hl
    sub 1
    jr exx__example_1
exx__example_2:
```

### Automatic branch selection

For both `asm` and `z80asm`, EXX emits `jr` for unconditional jumps and for
`Z`, `NZ`, `C`, or `NC` when the destination is −128 to +127 bytes from the
end of the instruction. This also applies to a tail jump to another procedure
in the same module. Other conditions, external destinations, and jumps across
a raw assembly block use `jp`. Instructions written inside `asm` pass through verbatim.

```text
choose(flag → Z) → A {
    if (flag) return 1
    return 2
}
```

```asm
choose:
    jr nz, exx__choose_1
    ld a, 1
    ret
exx__choose_1:
    ld a, 2
    ret
```

### Counted loops

`repeat` runs the body, then decrements B using `djnz`, preserving flags for the loop test. An
initial zero gives 256 iterations if the body leaves B alone. If the loop head is out of
range or its distance is unknown, `djnz` branches to a nearby `jp` back to the loop head.
When B reaches zero, a short `jr` skips that `jp`.

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
    jr z, exx__example_2
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

### Embedded structure fields

Declare an embedded field with its layout name and select its members with
a dot after the first field. EXX adds the assembler offsets along the path
and uses the size of the final field.

```text
field VID_SESSION.candidate: VID_SURFACE
field VID_SURFACE.mode: u16

set_mode(session: VID_SESSION → IX, mode → HL) {
    session->candidate.mode = mode
}
```

```asm
set_mode:
    ld (ix + VID_SESSION.candidate + VID_SURFACE.mode), l
    ld (ix + VID_SESSION.candidate + VID_SURFACE.mode + 1), h
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
    jr z, exx__example_1
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
python3 -m unittest discover -s tests
```

### Binary comparison

The assembly check compares both binaries for every example. The DuoConf fixture supplies
matching layout constants and four external helper stubs at the same addresses. Put sjasmplus
and z88dk-z80asm on PATH or select them with `--sjasmplus PATH` and `--z80asm PATH`.

```sh
python3 tests/assemble_examples.py
```

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
