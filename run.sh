#!/usr/bin/env bash
# Run the email checker using the project-local venv.
# Usage:
#   ./run.sh check
#   ./run.sh watch
#   ./run.sh status
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  echo "No .venv found. Run ./setup.sh first." >&2
  exit 1
fi

# Keep pip/python caches inside the project (Raspberry Pi SD-card friendly)
export PIP_CACHE_DIR="$ROOT/.pip-cache"
export PYTHONPYCACHEPREFIX="$ROOT/.pycache"
export TMPDIR="$ROOT/.tmp"
mkdir -p "$TMPDIR"

# shellcheck disable=SC1091
source .venv/bin/activate
exec python main.py "$@"
