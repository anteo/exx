.PHONY: build install install-local

VSCE ?= npx --yes @vscode/vsce@3.9.2
CODE ?=
export CODE
BUILD_DIR = ../../../build

build:
	mkdir -p "$(BUILD_DIR)"
	$(VSCE) package --no-dependencies --out "$(BUILD_DIR)/exx.vsix"

install:
	@cli="$$CODE"; \
	if [ -z "$$cli" ]; then \
		cli=$$(command -v code || true); \
	fi; \
	if [ -z "$$cli" ]; then \
		for app in '/Applications/Visual Studio Code.app' "$$HOME/Applications/Visual Studio Code.app"; do \
			if [ -d "$$app" ]; then \
				cli="$$app/Contents/Resources/app/bin/code"; \
				break; \
			fi; \
		done; \
	fi; \
	if [ -n "$$cli" ]; then \
		EXX_VSCODE_CLI="$$cli" $(MAKE) install-local; \
	else \
		printf '%s\n' 'VS Code not found. Skipping EXX extension.'; \
	fi

install-local: build
	"$$EXX_VSCODE_CLI" --install-extension "$(BUILD_DIR)/exx.vsix" --force
