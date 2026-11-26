#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
    echo "EXX Quick Look requires macOS." >&2
    exit 1
fi

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
applications="$HOME/Applications"
app_name="EXX File Type.app"
extension_name="EXX Preview.appex"
app_id="local.anteo.exx-file-type"
destination="$applications/$app_name"
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

built_app=${1:-"$src/../../build/quicklook/$app_name"}
if [[ $# -eq 0 ]]; then
    make -C "$src" build
fi

mkdir -p "$applications"
stage="$applications/.exx-quicklook-install"
if ! mkdir "$stage"; then
    echo "Another installation is active or left files in $stage." >&2
    exit 1
fi
app="$stage/$app_name"
previous="$stage/Previous.app"
replacing=no
installed=no

register() {
    "$lsregister" -f "$destination" &&
        /usr/bin/pluginkit -a "$destination/Contents/PlugIns/$extension_name" &&
        /usr/bin/pluginkit -e use -i "$app_id.quick-look" &&
        /usr/bin/qlmanage -r
}

cleanup() {
    if [[ "$installed" == no ]]; then
        if [[ "$replacing" == yes && -e "$destination" ]]; then
            /usr/bin/pluginkit -r "$destination/Contents/PlugIns/$extension_name" || true
            "$lsregister" -u "$destination" || true
            mv "$destination" "$stage/Failed.app" || return
        fi
        if [[ -e "$previous" ]]; then
            if ! mv "$previous" "$destination"; then
                echo "The previous app is saved in $previous." >&2
                return
            fi
            register || echo "Could not re-register the previous Quick Look extension." >&2
        fi
    fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -e "$destination" || -L "$destination" ]]; then
    if [[ -L "$destination" ]] ||
        [[ "$(plutil -extract CFBundleIdentifier raw -o - "$destination/Contents/Info.plist")" != "$app_id" ]]; then
        echo "A different app is installed at $destination." >&2
        exit 1
    fi
fi

/usr/bin/ditto "$built_app" "$app"

if [[ -e "$destination" ]]; then
    mv "$destination" "$previous"
fi
replacing=yes
mv "$app" "$destination"
register
installed=yes
echo "Installed EXX Quick Look in $destination."
