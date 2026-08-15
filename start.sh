#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in the values." >&2
  exit 1
fi

# Create/activate a virtualenv if needed
if [ ! -d .venv ]; then
  python -m venv .venv
fi
source .venv/bin/activate
pip install -e ".[dev]"

# Run the shared runtime (Discord bot + webhook server)
python -m main