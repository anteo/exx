.PHONY: release test test-asm quicklook quicklook-install

release:
	$(MAKE) -C tools/versioning release

test test-asm:
	$(MAKE) -C tests $@

quicklook:
	$(MAKE) -C tools/macos-quicklook build

quicklook-install:
	$(MAKE) -C tools/macos-quicklook install
