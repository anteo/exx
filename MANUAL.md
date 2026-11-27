# EXX Syntax

[![English](https://img.shields.io/badge/lang-en-blue.svg)](MANUAL.md) [![Русский](https://img.shields.io/badge/lang-ru-green.svg)](MANUAL.ru.md)

[EXX overview](README.md)
[Quick reference for coding agents](QUICK_REFERENCE.md)

## Reading the examples

Each EXX example is followed by output from the `asm` target unless another target is named.
For procedure-body fragments, the listing shows the corresponding instructions and branch
labels. The enclosing procedure’s entry label and implicit final `ret` are omitted.
In these fragments `session` is a `VID_SESSION` pointer in IX and `packet` is a `PACKET` pointer in IY.

## Procedures and registers

### Register ABI

Write the result before the procedure name in definitions and `extern`
declarations. Use a register or flag name for one result, as in `A read_byte()`,
and a parenthesized list for multiple results, as in `(CF, A) probe()`. Start
with the procedure name when it has no result, as in `reset()`. Parameter
arrows bind arguments to registers. `clobbers(...)` describes the procedure's
register and flag effects and follows the parameter list.

```text
extern (CF, A) video_stack_safe(window → B, session: VID_SESSION → IX) clobbers(C, HL, F)

(CF, A) check_window(window → B, session: VID_SESSION → IX) clobbers(C, HL, F) {
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

### Source comments

All targets copy `//` and `/* … */` comments into the assembly as semicolon-prefixed lines.
Procedure descriptions appear above their labels. A comment on a statement that emits no
code stays in source order alongside the remaining instructions.

```text
// Return the page number supplied by the caller.
A read_page(page → E) {
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
A read_page(page → E) { return page }
```

```asm
read_page:
    ld a, e
    ret
```

### Packed stack parameters

A typed parameter without a register binding occupies a stack slot. EXX starts
at offset 2 from SP on entry, just past the return address. It lays out stack
parameters in declaration order without padding. A `u8` occupies one byte, a
`u16` occupies two bytes in little-endian order, and register parameters take
no stack space. Use `frame(IX)` or `frame(IY)` to read the argument slots.

```text
A read_character(mode: u8, pointer: u16, character: u8)
    frame(IX) clobbers(CF, HF, N) {
    return character
}
```

```asm
read_character:
    push ix
    ld ix, 0
    add ix, sp
    ld a, (ix + 7)
    pop ix
    ret
```

### Explicit stack slots

`name: type → stack[n]` sets the byte offset from entry SP. Offsets 0 and 1 hold
the return address. Slots must be disjoint. An implicit slot starts after all
stack slots declared so far, including any explicitly placed ones. An `extern`
declaration may express the same offsets in either form.

```text
HL read_length(length: u16 → stack[6]) frame(IY) {
    return length
}
```

```asm
read_length:
    push iy
    push af
    ld iy, 2
    add iy, sp
    pop af
    ld l, (iy + 8)
    ld h, (iy + 8 + 1)
    pop iy
    ret
```

### Stack frames

`frame(IX)` or `frame(IY)` follows the parameter list and precedes
`clobbers(...)`. The selected register points to its saved caller value.
Arguments are therefore two bytes farther from the frame register than from
entry SP. All bytes of a declared slot must fit the Z80 index displacement
range. The frame register is available to the body and to register-ABI helpers
that preserve it. EXX restores it on early returns, fallthrough, and tail jumps.

```text
extern inspect(frame_pointer → IY)
A read_byte(value: u8) frame(IY) clobbers(CF, HF, N) {
    inspect(IY)
    A = value
}
```

```asm
read_byte:
    push iy
    ld iy, 0
    add iy, sp
    call inspect
    ld a, (iy + 4)
    pop iy
    ret
```

If any of CF, HF, and N is an input or must be preserved, the prologue saves and
restores AF around the address calculation, as in `read_length`. The frame
register must be preserved by the procedure's ABI. A definition with unused
stack parameters can omit the frame. Stack parameters are read-only. The
caller removes the argument bytes after the return.

### Calling with stack arguments

Write arguments in the order of the callee's signature. EXX lays the stack
arguments out by their declared offsets and evaluates them from the highest
address to the lowest. Pass a register of the required width, or prepare it
in place with `(register = expression)`. An unpaired byte must be in A, B, D,
or H. A word can use BC, DE, HL, IX, or IY. Explicit stack slots can leave
padding bytes, whose values are unspecified.

```text
extern (CF, A) probe(word: u16, tag: u8)
(CF, A) relay(word → HL, tag → A) { return probe(word, tag) }
```

```asm
relay:
    push af
    inc sp
    push hl
    call probe
    inc sp
    inc sp
    inc sp
    ret
```

EXX merges two adjacent bytes into a single `push` when the lower-addressed
byte is already in the low register of BC, DE, or HL and the other byte is
in its high register. Inline assignments keep their named registers and
evaluation order. Register arguments are delivered after preparing the stack.
Any explicit register-argument assignments run in signature order and must
preserve the arguments already set up, including ones passed as bare registers.

The generated call removes its outgoing bytes with `inc sp`, preserving the
returned registers and flags. `return callee(...)` with stack arguments emits
the call, cleanup and return in that order.

### Passing a structure by value

Use `TYPE { field: value, … }` for a stack parameter whose layout is defined
by `struct`. Name every field once. Separate fields with newlines, commas,
or semicolons. Field evaluation follows stack offset order, regardless of
how the fields are listed. Nested structures use the same notation.

```text
struct SURFACE { mode: u8, page0: u8, page1: u8 }
extern paint(surface: SURFACE, x: u8)
extern data draw

forward(page1 → C, x → B) clobbers(HL) {
    head → HL
    head = *(&draw)
    paint(SURFACE { mode: head.lo, page0: head.hi, page1: page1 }, x)
}
```

```asm
forward:
    ld hl, (draw)
    push bc
    push hl
    call paint
    inc sp
    inc sp
    inc sp
    inc sp
    ret
```

The destination width makes `head = *(&draw)` a word load. The two pushes
carry `page1, x` and `mode, page0` respectively. An assembler-owned layout
declared with `layout` and `field` can be read in a callee. Use an `asm`
block to pass it by value when EXX lacks its field offsets.

### Sizes of structures passed on the stack

`layout NAME: size` gives EXX the byte size it needs to place a by-value
argument on the stack. `field` declares the type of a member selected with a
dot, such as `surface.page0`. A member without a `field` declaration defaults
to `u8`. The `layout` and `field` declarations can go in a shared EXX ABI file.

```text
layout DRAW_SURFACE: 3
field DRAW_SURFACE.page0: u8

A read_page(mode: u8, surface: DRAW_SURFACE) frame(IX) clobbers(CF, HF, N) {
    return surface.page0
}
```

The assembler also needs the member's byte offset. For this example, the
assembler input or an included file supplies the following definition:

```asm
DRAW_SURFACE.page0 equ 1
```

For z88dk-z80asm, write `DEFC DRAW_SURFACE_page0 = 1`.

```asm
read_page:
    push ix
    ld ix, 0
    add ix, sp
    ld a, (ix + 5 + DRAW_SURFACE.page0)
    pop ix
    ret
```

### Grouped layouts

Use `layout { … }` to declare several ASM-owned sizes. A size declaration
can include the types of the fields used by EXX. The assembler still supplies
each field's byte offset. This example makes `address` a word at the existing
symbol `EXTERNAL_CELL.address`.

```text
layout {
    EXTERNAL_CELL: 5 { address: u16 }
    DRAW_SURFACE: 3
}

HL read_address(cell: EXTERNAL_CELL → IY) { return cell->address }
```

```asm
read_address:
    ld l, (iy + EXTERNAL_CELL.address)
    ld h, (iy + EXTERNAL_CELL.address + 1)
    ret
```

### Grouped field types

`field LAYOUT { … }` describes several members without repeating the layout
name. An outer `field { … }` accepts both grouped and qualified entries.
A field of a structure type provides the type for the next step of a member
path. Newlines, commas or semicolons separate entries in declaration blocks.

```text
field {
    VID_SESSION { candidate: DRAW_SURFACE }
    DRAW_SURFACE.page0: u8
}

A read_page(session: VID_SESSION → IX) { return session->candidate.page0 }
```

```asm
read_page:
    ld a, (ix + VID_SESSION.candidate + DRAW_SURFACE.page0)
    ret
```

### EXX structures

`struct` lays out `u8`, little-endian `u16` and other sized types in declaration
order without padding. A sized ASM-owned layout can be embedded as an opaque
field. The name of an EXX structure is its size, and paths such as
`DRAW_SURFACE.page0` are its field offsets in constant expressions.

```text
struct DRAW_SURFACE {
    mode: u8
    page0: u8
    page1: u8
}

A read_first_page(surface: DRAW_SURFACE → IX) { return surface->page0 }
```

Output for `sjasmplus`, with the generated include guard omitted from the listing.

```asm
    STRUCT @DRAW_SURFACE
mode BYTE
page0 BYTE
page1 BYTE
    ENDS

read_first_page:
    ld a, (ix + 1)
    ret
```

`z80asm` emits a `DEFVARS` block for the members and a `DEFC` for the size.
Use dotted field names in sjasmplus and underscore-separated names in
z88dk-z80asm. For the portable `asm` target, EXX uses numeric offsets in its
own instructions. See [sharing structures with ASM](README.md#sharing-structures-with-asm).

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

### Register-pair bytes

An alias for BC, DE or HL exposes its low byte as `.lo` and its high byte as
`.hi`. These operands read and write the underlying byte registers. The same
notation works for register parameters and in an inline `asm` contract.

```text
(A, HL) copy_high(addr → HL) {
    A = addr.hi
    addr.lo = A
}
```

```asm
copy_high:
    ld a, h
    ld l, a
    ret
```

A stack structure can still contain fields named `lo` or `hi`. For example,
`surface.lo` reads the field when `surface` is passed by value on the stack.

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
(CF, A) status(carry → CF) { return (carry, 5) }
```

```asm
status:
    ld a, 5
    ret
```

### Returning values already in registers

`return` by itself returns the current values in the registers and flags named
in the procedure signature. EXX checks that every declared result is available
on every path to that statement. Here both results come from the caller.

```text
(CF, BC) relay(carry → CF, cursor → BC) { return }
```

```asm
relay:
    ret
```

### Returning at the end of a procedure

Reaching the closing `}` returns the current values in the declared result
registers and flags. EXX checks that those values are available on every path
that reaches the closing brace. Use `return` to leave the procedure early.

```text
A read_byte(byte → E) {
    A = byte
}
```

```asm
read_byte:
    ld a, e
    ret
```

### Capturing call results

List all result locations in declaration order. A standalone call discards the results. Document
conditional meanings such as an error code in A when CF is set.

```text
extern (A, HL, DE) query()
HL inspect() clobbers(A, DE) {
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

Returning a register-only call with a matching result ABI generates a jump.
The destination must be reachable in the active memory map.

```text
extern A read_byte()
A fetch() { return read_byte() }
```

```asm
fetch:
    jp read_byte
```

### Conditional calls

When a branch only calls a procedure, EXX can emit a conditional `call`.
Register results and clobbers apply on the path that makes the call.

```text
extern update()
refresh(ready → Z) { if (ready) update() }
```

```asm
refresh:
    call z, update
    ret
```

### Conditional tail calls

When the call can be made with the current register and stack state, EXX
can fold a guarded tail call into a conditional jump. A nearby procedure
in the same module can use `jr` under the usual branch selection rules.

```text
extern A read_byte()
A fetch(ready → Z) {
    if (ready) return read_byte()
    return 0
}
```

```asm
fetch:
    jp z, read_byte
    ld a, 0
    ret
```

### Clobber declarations

`clobbers` permits changes visible to the caller. A result remains available even if its
register also appears in `clobbers`. F covers the six documented flags. AF, BC, DE and HL
overlap their components.

```text
extern (CF, A) probe() clobbers(HL, F)
```

An `extern` declaration emits no instructions. Calling `probe` from a `z80asm` module adds `EXTERN probe` to its header.

### Importing ABI declarations

Use `use "path.abi"` at file scope in an EXX source or ABI file. A relative
path starts at the directory of the file containing the `use`. The same ABI
file is loaded once even if it is reached through several imports or also
passed with `--abi`. Cycles and conflicting declarations are errors.

```text
// abi/video.abi
extern A read_page(page → E)
```

```text
// caller.exx
use "abi/video.abi"
A fetch_page(page → E) { return read_page(page) }
```

```asm
fetch_page:
    jp read_page
```

To import several files together, separate the paths with newlines, commas,
or semicolons.

```text
use {
    "abi/video.abi"
    "abi/console.abi"
}
```

An ABI file can contain `extern` procedure and data declarations, `struct`,
`layout`, `field`, `const`, and `use`. Assemble or link the implementation
separately. The `use` directive itself emits no assembler `INCLUDE`.

### Definite assignment

A read requires a value on every incoming path, including loop back edges. After `work()` the
caller must initialize D before returning DE.

```text
extern work() clobbers(D)
DE reset_high(word → DE) {
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

### Conditional branching

`if` executes its body when the condition is true. In this example the body
returns 1 when Z is set. Execution continues after the body when Z is clear.

```text
A choose(flag → Z) {
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

### Post-test loops

`do { … } while (condition)` executes the body once before testing. The
condition can use flags produced at the end of the body. Here each iteration
writes a space, then tests whether the updated cursor reached a tab stop.

```text
extern data __console_x: u8
extern put_cell(character → A) clobbers(AF, BC, DE, HL)

tab() clobbers(AF, BC, DE, HL) {
    do {
        A = 0x20
        put_cell(A)
        A = __console_x
        A &= 7
    } while (!Z)
}
```

```asm
tab:
exx__tab_1:
    ld a, 32
    call put_cell
    ld a, (__console_x)
    and 7
    jr nz, exx__tab_1
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

`break` exits the innermost loop. Here a zero byte exits before either HL or B changes.

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

### Local labels and goto

Use a label and `goto` for a shared exit or a local back edge. A jump can
stay in its block or go to an enclosing block in the same procedure.
An exit restores the pairs in any `keep` blocks it leaves. EXX checks
register availability and stack state at the destination.

The `sjasmplus` target emits procedure-local labels such as `.exx__1`, and
`z80asm` emits `@exx__1`. The generic `asm` target and procedures containing
an `asm` block use unique names such as `exx__fallback_1`. A label in inline
assembly can change the scope of native local labels.

```text
A fallback(ready → Z) {
    if (!ready) goto failed
    return 1
failed:
    return 0
}
```

```asm
fallback:
    jr nz, exx__fallback_1
    ld a, 1
    ret
exx__fallback_1:
    ld a, 0
    ret
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
A previous(cursor → IX) { return cursor[-1] }
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
A config(ctx: VID_CTX → IY) { return ctx->config }
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
HL table_address() { return &bs_storage_ops }
```

```asm
table_address:
    ld hl, bs_storage_ops
    ret
```

### Static data definitions

Use `data` at file scope to define an initialized byte or word. Its
initializer may be a constant expression or, for a word, a data address.
The definition is emitted in source order in the selected section.
Use `name` for the stored value and `&name` for its address.

```text
data cursor: u16 = 0x4000
HL load_cursor() { return cursor }
```

```asm
cursor:
    defw 16384

load_cursor:
    ld hl, (cursor)
    ret
```

### Typed external data

Declare the size of a symbol defined in another module to read or write
its contents. On Z80, absolute byte loads and stores use A. Word loads and
stores use a supported register pair.

```text
extern data status: u8
set_status(value → A) { status = value }
```

```asm
set_status:
    ld (status), a
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

### Constants declared in EXX

Declare one constant with `const NAME = expression` or put several in a
`const { … }` block. Constant expressions can use integer arithmetic,
other constants, and structure sizes and offsets. EXX emits `EQU` or `DEFC`
for definitions in the source being translated.

```text
const {
    SCREEN = 0x4000
    ATTRIBUTES = SCREEN + 0x1800
}
```

```asm
SCREEN EQU 16384
ATTRIBUTES EQU 22528
```

### Assembly origin

`origin expression` emits `ORG` at that point in the source. The assembler
applies its own placement rules. z88dk-z80asm can emit a separate binary for
a section with an explicit origin.

```text
origin 0x8000
data marker: u8 = 42
```

```asm
    ORG 32768
marker:
    defb 42
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

Choose the destination explicitly. EXX loads the left operand into A before
adding C. The load must preserve the right operand.

```text
A = B + C
```

```asm
    ld a, b
    add a, c
```

### Prefix increment

`++reg` increments a register or register alias in place and produces its new
value. Use it on its own, in an assignment, or in a condition. The result wraps
at the register's width. Byte `inc` updates the other arithmetic flags and
preserves CF. Word `inc` preserves all flags.

```text
if ((A = ++column) < columns) return (CF, cursor)
```

```asm
    inc c
    ld a, c
    cp e
    ret c
```

Here `column` is C, `columns` is E, and `cursor` is BC. `cp e` sets the returned CF.

### Prefix decrement

`--reg` decrements a register or register alias in place and produces the new
value. Byte `dec` preserves CF. Word `dec` preserves all flags.

```text
HL shorten(remaining → HL) {
    --remaining
    return remaining
}
```

```asm
shorten:
    dec hl
    ret
```

### Postfix increment

`reg++` increments the register. To use the original value, assign it to a
separate register of the same width. This also works inside a parenthesized
assignment in a condition.

```text
if ((A = column++) < columns) return (CF, cursor)
```

```asm
    ld a, c
    inc c
    cp e
    ret c
```

### Postfix decrement

`reg--` decrements the register. A standalone statement discards the original
value. An assignment copies it to a separate register before decrementing.

```text
(A, B) take_count(count → B) clobbers(F) {
    A = count--
    return (A, count)
}
```

```asm
take_count:
    ld a, b
    dec b
    ret
```

### Assignment in arithmetic

A parenthesized assignment writes the named register and uses that register
as the operand. The expression evaluates operands from left to right and
checks that a nested assignment preserves any value or address still in use.

```text
IY adjust(base → IY) clobbers(DE, CF, HF, N) {
    base += (DE = BS_WORKSPACE_OFF + RST8_DATA_OFF)
    return base
}
```

```asm
adjust:
    ld de, 0 + (BS_WORKSPACE_OFF + RST8_DATA_OFF)
    add iy, de
    ret
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

### Register-pair copies

Copies between BC, DE and HL use two byte loads and preserve flags.

```text
HL copy_pair(src → BC) { return src }
```

```asm
copy_pair:
    ld h, b
    ld l, c
    ret
```

### Register-pair subtraction

Subtracting BC, DE or HL from HL clears carry, then uses `sbc`.
The sequence preserves A and sets the flags from the subtraction.

```text
HL remaining(size → HL, skip → DE) clobbers(F) {
    size -= skip
    return size
}
```

```asm
remaining:
    or a
    sbc hl, de
    ret
```

### Register-pair zero tests

Combine a pair's two bytes with OR in an assignment to A. The condition
uses the flags from that OR.

```text
A has_size(size → BC) clobbers(F) {
    if ((A = B | C)) return 1
    return 0
}
```

```asm
has_size:
    ld a, b
    or c
    jr z, exx__has_size_1
    ld a, 1
    ret
exx__has_size_1:
    ld a, 0
    ret
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

## Assembly blocks

### File-scope assembly

Use `asm { … }` to place tables, labels, macros or assembler directives between EXX procedures.
All targets emit the body in source order after the generated module header. Indentation, symbol
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
A invert(value → A) clobbers(HF, N) {
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
