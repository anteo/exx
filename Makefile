.PHONY: release

release: export EXX_RELEASE_VERSION := $(VERSION)
release:
	@tools/versioning/release.sh "$$EXX_RELEASE_VERSION"
