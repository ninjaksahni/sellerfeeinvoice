#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "No .venv found. Run: bash scripts/setup.sh"
  exit 1
fi

source .venv/bin/activate
unset PLAYWRIGHT_BROWSERS_PATH
exec streamlit run app.py "$@"
