#!/bin/zsh
set -eu
PROJECT_DIR="${0:A:h}"
exec "$PROJECT_DIR/runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3" -I -B "$PROJECT_DIR/tools/check.py" "$@"
