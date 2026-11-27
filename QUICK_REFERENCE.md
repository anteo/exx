# EXX quick reference for coding agents

Use EXX for Z80 routines whose register ABI and instruction sequence you can
describe explicitly. Read the existing callers and write down the inputs,
outputs, preserved state and flags before translating a routine. Use the
[syntax manual](MANUAL.md) for detailed rules and assembly listings.

## Procedures and ABI

```text
extern (CF, A) probe(window → B, context: CTX → IX) clobbers(HL, F)

(CF, A) check(window → B, context: CTX → IX) clobbers(HL, F) {
    (CF, A) = probe(window, context)
    if (CF) return
    return (0, 1)
}
```

- Write the result before the procedure name. Use `A read()`, `(CF, A) read()`
  or `clear()` for one result, multiple results or no results.
- `name → REG` binds a register. A local binding can bind several at once,
  as in `(column, row) → (C, B)`. Use `CF` for carry and `C` for the register.
  The modeled flags are `CF`, `Z`, `S`, `PV`, `HF` and `N`.
- For an alias of BC, DE or HL, `.lo` and `.hi` name writable byte registers.
  After `addr → HL`, `addr.lo = A` emits `ld l,a`.
- EXX checks call locations and clobbers. Prepare inputs explicitly, either
  before the call or with `(register = expression)` in the argument list.
- Use `return` or the closing brace when all declared results are defined.
  `return value` and `return (flag, value)` prepare results.
  `return callee(args)` requires matching results. Register-only calls can
  jump directly. Stack calls use `call`, clean up and return.
- `clobbers(F)` covers all flags. Include every caller-visible change,
  including changes caused by a comparison or a helper. For a call that
  clobbers a live register, preserve it with `keep` or reload it.

## Choose the Z80 operation explicitly

| Goal | EXX form and constraint |
| --- | --- |
| Branch on a flag | `if (CF) return` or `if (!Z) { … }`. Test the flag directly after its producer. |
| Compare unsigned bytes | `if (A < E) …` or `if ((A = value) == 5) …`. An operand must be A or its alias. `if (!A)` tests zero. |
| Walk a loop | `while (condition) { … }` tests first. `do { … } while (condition)` runs the body first. `repeat(B)` emits DJNZ semantics, including the initial-zero case. `break` exits the innermost loop. A local `name:` can be reached with `goto name`. |
| Move or update a value | `A = value`, `++row`, `A = row++`, `HL += DE`, `IY += (DE = OFFSET + BASE)`. Nested assignment makes the scratch register explicit. A postfix result needs a separate destination register. |
| Test or change bits | `if (value$3) …`, `value$3 = 1`, `A &= mask`, `A \|= mask`, `A ^= mask`, `A = ~A`. |
| Shift, rotate or use carry | `B >>= 2`, `sra(D)`, `rl(E)`, `rlc(B)`, `rr(E)`, `rrc(B)`, `adc(HL, DE)`, `sbc(A, E)`. Shift counts are compile-time integers. |
| Save and restore | `keep(BC, AF) { … }`, or balanced `push(BC)` and `pop(BC)`. `keep` restores on every exit from its block. |
| Exchange registers | `ex(DE, HL)`, `ex_sp(IX)`, `ex(AF)` and `exx()`. |
| Port and block operations | `D = in(BC)`, `out(0xFE, A)`, `ldir(DE, HL, BC)`, `cpir(HL, A, BC)`, `inir(HL, C, B)`, `otir(C, HL, B)`. A block operation also accepts empty parentheses. |

EXX chooses JR when it can prove the displacement fits and the condition
supports it. Check the listing when opcode choice, flags, size or timing matter.

## Memory, stack and declarations

- `A = *ptr` loads an indirect byte. `B = ptr[3]` needs IX or IY.
  For a typed register pointer, use `context->field` or `context->outer.inner`.
  A word field loads into BC, DE or HL as two byte operations.
- `value: u8` is an incoming packed stack argument. Use `value: u8 → stack[8]`
  for an explicit byte offset from entry SP. `frame(IX)` or `frame(IY)` is
  required to read incoming arguments. The caller removes them. A stack
  structure uses dot access, as in `surface.page0`.
- For `extern send(tag: u8, size: u16)`, call `send((A = tag), HL)`.
  Stack arguments are evaluated from highest to lowest offset. Put lone
  bytes in A, B, D or H. Adjacent low/high bytes already in BC, DE or HL
  share a `push`. EXX cleans up the arguments and preserves call results.
- For a stack parameter of native `struct` type, pass `CELL { ch: A, attr: H }`.
  Name all fields, using the same notation for a nested structure. To load
  two adjacent bytes explicitly, assign `head = *(&symbol)` to a word
  register alias and use `head.lo` and `head.hi` as the field values.
- `struct CELL { ch: u8, attr: u8 }` defines a packed layout owned by EXX.
  Native structs can contain other sized layouts. For a layout supplied by
  ASM, use `layout CELL: 2` and `field CELL.ch: u8`, or a grouped declaration
  such as `layout CELL: 2 { ch: u8, attr: u8 }`.
- `data mode: u8 = 0` allocates data. `extern data buffer` declares its address.
  With `extern data mode: u8`, `mode` reads the value and `&mode` gives its address.
- `const MASK = 0x80` and `const { MASK = 0x80, BIT = 7 }` emit constant
  definitions. `origin 0x8000` emits `ORG`.
- Put assembler-specific directives or unsupported operations in `asm { … }`.
  Inside a procedure, declare the effects, for example
  `asm(A) → A clobbers(HF, N) { cpl }`.

## Translate and inspect

```sh
./exx --target sjasmplus --abi shared.abi source.exx -o source.asm
./exx --target z80asm --section code_clib --abi shared.abi source.exx -o source.asm
./exx --target sjasmplus --layouts-only shared.abi -o shared.inc
```

Use the assembler target already selected by the project. `asm` emits a
generic assembly fragment. For a shared ABI, keep procedure declarations and
struct definitions in the same `.abi` sources used by every EXX caller.
Import them with `use "abi/video.abi"` or `use { "abi/video.abi", "abi/os.abi" }`.
Paths are relative to the file containing `use`, including inside ABI files.
The `--layouts-only` output lets ordinary ASM include those structures.

When porting an existing routine, compare the generated instructions with the
original and assemble them with the project's assembler. Check early exits,
carry and zero, preserved registers, stack balance, and any size or timing
constraints the routine depends on. Split expressions at register transfers
the Z80 must perform anyway. Use an inline ASM block with a contract when a
required sequence has no direct EXX form.
