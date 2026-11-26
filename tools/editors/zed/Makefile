.PHONY: build install install-local

PYTHON ?= python3
TREE_SITTER ?= tree-sitter
export ZED_EXTENSIONS_DIR

build:
	$(PYTHON) build.py --tree-sitter "$(TREE_SITTER)"

install:
	@if command -v zed >/dev/null 2>&1 || command -v zeditor >/dev/null 2>&1 || \
	    [ -d /Applications/Zed.app ] || [ -d "$$HOME/Applications/Zed.app" ]; then \
		$(MAKE) install-local; \
	else \
		printf '%s\n' 'Zed not found. Skipping EXX extension.'; \
	fi

install-local: build
	$(PYTHON) build.py --install
