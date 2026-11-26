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

mkdir -p "$applications"
stage="$applications/.exx-quicklook-install"
if ! mkdir "$stage"; then
    echo "Another installation is active or left files in $stage." >&2
    exit 1
fi
app="$stage/$app_name"
extension="$app/Contents/PlugIns/$extension_name"
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

mkdir -p "$app/Contents/MacOS" "$extension/Contents/MacOS"
cp "$src/App-Info.plist" "$app/Contents/Info.plist"
cp "$src/Preview-Info.plist" "$extension/Contents/Info.plist"
xcrun clang -mmacosx-version-min=12.0 "$src/AppMain.c" -o "$app/Contents/MacOS/EXXFileType"
xcrun swiftc -O -target "$(uname -m)-apple-macosx12.0" -parse-as-library \
    -module-name EXXPreview -application-extension -Xlinker -e -Xlinker _NSExtensionMain \
    "$src/PreviewProvider.swift" -o "$extension/Contents/MacOS/EXXPreview"
codesign --force --sign - --entitlements "$src/Preview.entitlements" "$extension"
codesign --force --sign - "$app"

if [[ -e "$destination" ]]; then
    mv "$destination" "$previous"
fi
replacing=yes
mv "$app" "$destination"
register
installed=yes
echo "Installed EXX Quick Look in $destination."
