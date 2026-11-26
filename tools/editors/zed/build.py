"""Build and register a local Zed language extension."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


SOURCE = Path(__file__).resolve().parent
OUTPUT = SOURCE.parents[2] / "build" / "zed"
EXTENSION = OUTPUT / "exx"


def zed_extensions_directory():
    override = os.environ.get("ZED_EXTENSIONS_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Zed" / "extensions"
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Zed" / "extensions"
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "zed" / "extensions"


def build(tree_sitter):
    grammar = OUTPUT / "tree-sitter-exx"
    grammar.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE / "grammar.js", grammar / "grammar.js")
    subprocess.run([tree_sitter, "generate", "--abi", "14"], cwd=grammar, check=True)

    # The Git snapshot lets Zed rebuild through its Dev Extension command.
    def git(*args, **options):
        return subprocess.run(["git", *args], cwd=grammar, check=True, text=True, **options)

    if not (grammar / ".git").exists():
        git("init", "--quiet")
    git("add", "--", "grammar.js", "src")
    tree = git("write-tree", capture_output=True).stdout.strip()
    previous = git("for-each-ref", "--format=%(tree)", "refs/heads/exx", capture_output=True)
    if previous.stdout.strip() != tree:
        commit = git("-c", "user.name=EXX build", "-c", "user.email=build@exx.invalid",
                     "commit-tree", tree, "-m", "Generate the EXX parser",
                     capture_output=True).stdout.strip()
        git("update-ref", "refs/heads/exx", commit)
    revision = git("rev-parse", "refs/heads/exx", capture_output=True).stdout.strip()

    grammars = EXTENSION / "grammars"
    grammars.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    sdk = zed_extensions_directory() / "build" / "wasi-sdk"
    clang = "clang.exe" if sys.platform == "win32" else "clang"
    if (sdk / "bin" / clang).is_file():
        env.setdefault("TREE_SITTER_WASI_SDK_PATH", str(sdk.resolve()))
    with TemporaryDirectory(dir=grammars) as directory:
        wasm = Path(directory) / "exx.wasm"
        subprocess.run([tree_sitter, "build", "--wasm", "--output", str(wasm), str(grammar)],
                       env=env, check=True)
        wasm.replace(grammars / wasm.name)

    shutil.copytree(SOURCE / "languages", EXTENSION / "languages", dirs_exist_ok=True)
    manifest = (SOURCE / "extension.toml").read_text(encoding="utf-8")
    manifest += (f"\n[grammars.exx]\nrepository = {json.dumps(grammar.as_uri())}\n"
                 f'rev = "{revision}"\n')
    (EXTENSION / "extension.toml").write_text(manifest, encoding="utf-8")
    print(f"Built Zed extension in {EXTENSION}")


def install():
    # Zed registers dev extensions as directory symlinks under installed/.
    installed = zed_extensions_directory() / "installed" / "exx"
    installed.parent.mkdir(parents=True, exist_ok=True)
    try:
        installed.symlink_to(EXTENSION, target_is_directory=True)
    except FileExistsError:
        if not installed.is_symlink() or installed.resolve() != EXTENSION:
            sys.exit(f"A different EXX extension is installed at {installed}.")
    os.utime(installed.parent)
    print(f"Registered Zed EXX extension at {installed}. Restart Zed if already open.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree-sitter", default="tree-sitter")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        if args.install:
            install()
        else:
            build(args.tree_sitter)
    except FileNotFoundError as error:
        sys.exit(f"Cannot find {error.filename}. Install the Tree-sitter CLI and Git.")
