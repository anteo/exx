.PHONY: editors install zed zed-install vscode vscode-install quicklook quicklook-install release test test-asm

editors: zed vscode
	$(MAKE) -C tools/macos-quicklook build-if-supported

install:
	$(MAKE) -k zed-install vscode-install

zed:
	$(MAKE) -C tools/editors/zed build

zed-install:
	$(MAKE) -C tools/editors/zed install

vscode:
	$(MAKE) -C tools/editors/vscode build

vscode-install:
	$(MAKE) -C tools/editors/vscode install

release:
	$(MAKE) -C tools/versioning release

test test-asm:
	$(MAKE) -C tests $@

quicklook:
	$(MAKE) -C tools/macos-quicklook build

quicklook-install:
	$(MAKE) -C tools/macos-quicklook install
