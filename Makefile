.PHONY: release test test-asm

PYTHON ?= python3

release: export EXX_RELEASE_VERSION := $(VERSION)
release:
	@tools/versioning/release.sh "$$EXX_RELEASE_VERSION"

test:
	$(PYTHON) -m unittest discover -s tests

test-asm:
	$(PYTHON) tests/assemble_examples.py
