#!/usr/bin/env bash
# Create a project-local venv and install dependencies.
# Nothing is written outside this folder except the system Python itself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Prefer python3 on PATH (Raspberry Pi OS / macOS / Linux)
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv in $ROOT/.venv"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Local config templates
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — fill in your API keys and email credentials."
fi
if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json — adjust importance criteria and interval if needed."
fi

mkdir -p data logs

echo
echo "Setup complete."
echo "  1. Edit .env        (AI key, Telegram, Gmail/Outlook passwords)"
echo "  2. Edit config.json (importance criteria, check interval)"
echo "  3. Run:  source .venv/bin/activate && python main.py check"
