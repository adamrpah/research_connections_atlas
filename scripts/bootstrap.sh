#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/ and rerun." >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js >=22.13 and npm are required." >&2
  exit 1
fi

mkdir -p data/Annual-Reports data/DigitalMeasure-Reports .secrets results
uv sync
npm --prefix webapp ci
if [[ ! -f webapp/public/data/manifest.json ]]; then
  mkdir -p webapp/public/data
  cp webapp/public/data/demo/*.json webapp/public/data/
fi
uv run python scripts/doctor.py

echo
echo "Bootstrap complete. Run: python3 scripts/doctor.py --strict"
echo "For topic modeling, also run: uv sync --extra topic"
