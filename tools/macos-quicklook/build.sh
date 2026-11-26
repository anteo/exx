#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
    echo "EXX Quick Look requires macOS." >&2
    exit 1
fi

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output=$1
app_name="EXX File Type.app"
mkdir -p "$output"
stage="$(mktemp -d "$output/.build.XXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
app="$stage/$app_name"
extension="$app/Contents/PlugIns/EXX Preview.appex"

mkdir -p "$app/Contents/MacOS" "$extension/Contents/MacOS"
cp "$src/App-Info.plist" "$app/Contents/Info.plist"
cp "$src/Preview-Info.plist" "$extension/Contents/Info.plist"
xcrun clang -mmacosx-version-min=12.0 "$src/AppMain.c" -o "$app/Contents/MacOS/EXXFileType"
xcrun swiftc -O -target "$(uname -m)-apple-macosx12.0" -parse-as-library \
    -module-name EXXPreview -application-extension -Xlinker -e -Xlinker _NSExtensionMain \
    "$src/PreviewProvider.swift" -o "$extension/Contents/MacOS/EXXPreview"
codesign --force --sign - --entitlements "$src/Preview.entitlements" "$extension"
codesign --force --sign - "$app"

rm -rf -- "$output/$app_name"
mv "$app" "$output/$app_name"
echo "Built EXX Quick Look in $output/$app_name."
