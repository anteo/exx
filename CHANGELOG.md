# Changelog

## v0.3.0

### Documentation

- (exx) add a quick reference for coding agents

### Features

- (syntax) return declared results at procedure exits
- (abi) support incoming stack arguments
- (layout) share structure declarations with assemblers
- (syntax) add constant and origin declarations
- (cli) configure generated assembly indentation
- (asm) emit procedure-local labels for native targets
- (syntax) support do-while loops
- (abi) import shared declarations with use
- (syntax) expose low and high bytes of register pairs
- (abi) lower outgoing stack arguments

## v0.2.1

### Features

- (syntax) **Breaking.** put procedure results before names
- (syntax) add register increment and decrement operators

### Fixes

- (highlight) style flags like registers
- (release) publish GitHub releases with changelog notes

### Tests

- (abi) use result prefixes in interface fixtures

## v0.2.0

### Documentation

- (readme) clarify generic Z80 assembly output

### Features

- (quicklook) add separate build and install targets
- (editors) add EXX highlighting for Zed and VS Code

### Fixes

- (release) push release commits and tags atomically

### Refactoring

- (build) delegate test and release targets

## v0.1.0

### Documentation

- (readme) document the compiler in English and Russian
- (readme) pair EXX examples with assembly and compare languages
- (exx) split syntax manuals from project documentation

### Features

- (compiler) translate register-bound EXX procedures to Z80 assembly
- (compiler) register backends and check shared procedure contracts
- (z80) support bit operations and carry arithmetic
- (compiler) add typed memory access and counted loops
- (z80) track stack transfers and support port and block operations
- (compiler) preserve register pairs across scoped exits with keep
- (codegen) preserve source comments in generated assembly
- (compiler) support native assembly blocks with register contracts
- (z80) select short branches when destinations are in range
- (compiler) support embedded structure fields
- (z80) lower register-pair copies and arithmetic
- (z80) fold guarded calls and tail jumps
- (compiler) allow nested assignments in arithmetic
- (compiler) support local labels and checked goto
- (compiler) define and access typed static data
- (quicklook) add macOS previews for EXX sources
- (release) add EXX versioning and local release workflow

### Tests

- (codegen) compare example output with assembly fixtures
- (build) expose test suites through Make

