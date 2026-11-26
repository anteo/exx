# Changelog

## Unreleased

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

### Tests

- (codegen) compare example output with assembly fixtures
