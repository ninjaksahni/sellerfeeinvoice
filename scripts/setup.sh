#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

unset PLAYWRIGHT_BROWSERS_PATH
playwright install chromium

echo ""
echo "Setup complete. Run: streamlit run app.py"
