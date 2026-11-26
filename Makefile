.PHONY: release test test-asm

release:
	$(MAKE) -C tools/versioning release

test test-asm:
	$(MAKE) -C tests $@
