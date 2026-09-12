#!/bin/bash
set -euo pipefail
action="${1:?Expected install, doctor or uninstall}"
shift
case "$action" in install|doctor|uninstall) ;; *) echo 'Unknown action' >&2; exit 1;; esac
if [ "$(uname -s)" != Darwin ]; then
    echo 'This installer supports macOS. On Windows use install.ps1.' >&2
    exit 1
fi
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
studio_root="$HOME/Library/Application Support/RhinoMCPStudio"
arguments=("$@")
while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-root) studio_root="${2:?Missing --install-root value}"; shift 2;;
        --install-root=*) studio_root="${1#*=}"; shift;;
        *) shift;;
    esac
done
case "$studio_root" in /*) ;; *) echo '--install-root must be an absolute path' >&2; exit 1;; esac
if [ -z "$studio_root" ] || [ "$studio_root" = / ] || [ "$studio_root" = "$HOME" ] || [[ "$studio_root" == *'/../'* ]] || [[ "$studio_root" == */.. ]]; then
    echo 'Unsafe installation directory' >&2
    exit 1
fi
studio_root="${studio_root%/}"
if [ -z "$studio_root" ] || [ "$studio_root" = / ] || [ "$studio_root" = "$HOME" ]; then
    echo 'Unsafe installation directory' >&2; exit 1
fi
ancestor="$studio_root"
while [ "$ancestor" != / ] && [ -n "$ancestor" ]; do
    if [ -L "$ancestor" ]; then echo "Directory cannot use a symlink: $ancestor" >&2; exit 1; fi
    ancestor="$(dirname -- "$ancestor")"
done
marker="$studio_root/.rhinomcp-studio-root"
if [ -d "$studio_root" ] && [ -n "$(ls -A "$studio_root")" ]; then
    if [ ! -f "$marker" ] || [ "$(cat "$marker")" != 'RhinoMCP Studio managed installation' ]; then
        echo "Refusing a directory not owned by Studio: $studio_root" >&2; exit 1
    fi
fi
studio_uv="$studio_root/bootstrap/uv"
uv_version=0.11.28
python_version=3.12.12
export UV_PYTHON_INSTALL_DIR="$studio_root/runtime"
export UV_CACHE_DIR="$studio_root/cache"
export UV_NO_CONFIG=1
export PYTHONUTF8=1
if [ "$action" = install ]; then
    mkdir -p "$studio_root/bootstrap"
    printf 'RhinoMCP Studio managed installation\n' > "$marker"
    if [ ! -x "$studio_uv" ]; then
        case "$(uname -m)" in
            arm64) target=aarch64-apple-darwin; expected=33540eb7c883ab857eff79bd5ac2aa31fe27b595abecb4a9c003a2c998447232;;
            x86_64) target=x86_64-apple-darwin; expected=2ad79983127ffca7d77b77ce6a24278d7e4f7b817a1acf72fea5f8124b4aac5e;;
            *) echo 'Unsupported architecture' >&2; exit 1;;
        esac
        archive="$studio_root/bootstrap/uv.tar.gz"
        asset="https://github.com/astral-sh/uv/releases/download/$uv_version/uv-$target.tar.gz"
        curl --fail --location --proto '=https' --tlsv1.2 "$asset" -o "$archive"
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
        if [ "$expected" != "$actual" ]; then echo 'uv checksum mismatch' >&2; exit 1; fi
        tar -xzf "$archive" -C "$studio_root/bootstrap" --strip-components=1
        rm -- "$archive"
    fi
    case "$("$studio_uv" --version)" in "uv $uv_version"|"uv $uv_version "*) ;; *) echo 'Unexpected private uv version' >&2; exit 1;; esac
    "$studio_uv" python install "$python_version" --no-bin --no-registry
elif [ ! -x "$studio_uv" ]; then
    echo 'Private installer runtime was not found. Rerun install.sh to repair.' >&2; exit 1
fi
studio_python="$("$studio_uv" python find --no-project --managed-python --no-python-downloads "$python_version")"
"$studio_python" "$script_dir/manager.py" "$action" --install-root "$studio_root" --uv "$studio_uv" --bundle "$script_dir" "${arguments[@]}"
if [ "$action" = uninstall ]; then
    if [ "$(cd -- "$studio_root" && pwd -P)" != "$studio_root" ] || [ "$(cat "$marker")" != 'RhinoMCP Studio managed installation' ] || [ -e "$studio_root/state.json" ]; then
        echo 'Cleanup target changed; private runtime was preserved.' >&2; exit 1
    fi
    rm -rf -- "$studio_root"
    echo 'RhinoMCP Studio private files removed.'
fi
