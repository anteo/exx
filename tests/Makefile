.PHONY: test test-asm

PYTHON ?= python3

test:
	cd .. && $(PYTHON) -m unittest discover -s tests

test-asm:
	cd .. && $(PYTHON) tests/assemble_examples.py
