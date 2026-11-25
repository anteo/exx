# Declare the source as the first prerequisite and $(EXX_TOOL_DEPS) after it.
# Call $(exx_compile) in the recipe of the generated assembly file.

EXX_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
EXX ?= $(EXX_ROOT)/exx
EXX_TOOL_DEPS ?= $(EXX) $(wildcard $(EXX_ROOT)/exxlang/*.py)
EXX_TARGET ?= sjasmplus
EXX_FLAGS ?=

define exx_compile
	mkdir -p "$(@D)"
	"$(EXX)" --target "$(EXX_TARGET)" $(EXX_FLAGS) "$<" -o "$@"
endef
