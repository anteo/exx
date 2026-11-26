.PHONY: build build-if-supported install

BUILD_DIR = ../../build/quicklook

build:
	bash build.sh "$(BUILD_DIR)"

build-if-supported:
ifeq ($(shell uname -s),Darwin)
build-if-supported: build
endif

install: build
	./install.sh "$(BUILD_DIR)/EXX File Type.app"
