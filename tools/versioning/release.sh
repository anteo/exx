#!/bin/sh
set -eu

version=${1:-}
if [ -z "$version" ]; then
    printf '%s\n' 'Usage: make release VERSION=<MAJOR.MINOR.PATCH|patch|minor|major>' >&2
    exit 2
fi

CDPATH= cd -- "$(dirname -- "$0")/../.."
bump_my_version=${BUMP_MY_VERSION:-bump-my-version}
git_cliff=${GIT_CLIFF:-git-cliff}
version_file=exxlang/__init__.py
bump_config=tools/versioning/bumpversion.toml
changelog=CHANGELOG.md

read_version() {
    sed -n 's/^__version__ = "\([^"]*\)"$/\1/p'
}

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 ||
        fail "Cannot find '$1'. Install $2 or set $3 to its executable path."
}

head=$(git rev-parse HEAD)
lock=$(git rev-parse --git-common-dir)/exx-release.lock
mkdir "$lock" || fail "Another EXX release is active or left files in $lock."
release_log="$lock/CHANGELOG.md"
restore=no
cleanup() {
    if [ "$restore" = yes ] && [ "$(git rev-parse HEAD)" = "$head" ]; then
        git restore --source="$head" --staged --worktree -- "$version_file" "$bump_config" "$changelog" ||
            printf '%s\n' 'Could not restore the release files.' >&2
    fi
    rm -f -- "$release_log"
    rmdir -- "$lock"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[ -z "$(git status --porcelain)" ] || fail 'Commit local changes before preparing the release.'
git ls-files --error-unmatch -- "$version_file" "$bump_config" "$changelog" >/dev/null
case "$version" in
    patch|minor|major)
        require_tool "$bump_my_version" bump-my-version BUMP_MY_VERSION
        version=$("$bump_my_version" show --config-file "$bump_config" \
            --increment "$version" new_version)
        ;;
esac
case "$version" in ''|*[!0-9.]*) fail "Invalid EXX version: $version" ;; esac
printf '%s\n' "$version" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' ||
    fail "Invalid EXX version: $version"

tag="v$version"
ref="refs/tags/$tag"
printf 'Release version %s\n' "$version"

if git show-ref --verify --quiet "$ref"; then
    [ "$(git cat-file -t "$ref")" = tag ] || fail "$tag must be annotated."
    [ "$(git rev-parse "$ref^{commit}")" = "$head" ] || fail "$tag points to a different commit."
else
    require_tool "$bump_my_version" bump-my-version BUMP_MY_VERSION
    require_tool "$git_cliff" git-cliff GIT_CLIFF
    current=$("$bump_my_version" show --config-file "$bump_config" current_version)
    [ "$(read_version < "$version_file")" = "$current" ] || fail 'The EXX version and bump configuration differ.'

    "$git_cliff" --config tools/versioning/cliff.toml --use-branch-tags --tag "$tag" --output "$release_log"
    grep -Fxq "## $tag" "$release_log" || fail "No changelog section was generated for $tag."
    restore=yes
    if [ "$version" != "$current" ]; then
        "$bump_my_version" bump --config-file "$bump_config" --no-commit --no-tag --new-version "$version"
    fi
    [ "$(read_version < "$version_file")" = "$version" ] || fail "$version_file must contain EXX version $version."
    cp "$release_log" "$changelog"

    git add -- "$version_file" "$bump_config" "$changelog"
    if ! git diff --cached --quiet; then
        git commit -m "chore(release): release $version"
    fi
    restore=no
fi

commit=$(git rev-parse HEAD)
[ "$(git show "$commit:$version_file" | read_version)" = "$version" ] ||
    fail "HEAD must contain EXX version $version."
git show "$commit:$changelog" | grep -Fxq "## $tag" || fail "HEAD must contain the changelog for $tag."
if ! git show-ref --verify --quiet "$ref"; then
    git tag -a "$tag" -m "$tag" "$commit"
fi
printf 'Local release %s at %s\n' "$tag" "$commit"
