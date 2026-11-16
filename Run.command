#!/bin/zsh
set -eu
PROJECT_DIR="${0:A:h}"
PYTHON="$PROJECT_DIR/runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  print -u2 'Эта автономная сборка предназначена для Mac с чипом M (Apple Silicon).'
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  print -u2 'Не найден вложенный Python. Перенеси всю папку Pokemon-Red целиком.'
  exit 1
fi
exec "$PROJECT_DIR/Pokemon.app/Contents/MacOS/Pokemon" "$@"
