# Declare the source as the first prerequisite and $(EXX_TOOL_DEPS) after it.
# Call $(exx_compile) in the recipe of the generated assembly file.

EXX_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EXX ?= $(EXX_ROOT)/exx
EXX_ABI ?=
EXX_TOOL_DEPS ?= $(EXX) $(wildcard $(EXX_ROOT)/exxlang/*.py $(EXX_ROOT)/exxlang/platforms/*.py $(EXX_ROOT)/exxlang/targets/*.py) $(EXX_ABI)
EXX_TARGET ?= asm
EXX_FLAGS ?=

define exx_compile
	mkdir -p "$(@D)"
	"$(EXX)" --target "$(EXX_TARGET)" $(foreach file,$(EXX_ABI),--abi "$(file)") $(EXX_FLAGS) "$<" -o "$@"
endef
