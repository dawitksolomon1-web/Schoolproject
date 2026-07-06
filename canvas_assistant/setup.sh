#!/usr/bin/env bash
# One-time setup for the Canvas Homework Assistant (macOS / Linux).
# Run from inside the canvas_assistant folder:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing dependencies (first run takes a few minutes)..."
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python -m playwright install chromium

if [ ! -f .env ]; then
    cp .env.example .env
    read -r -p "Your Canvas URL (press Enter for https://umd.instructure.com): " url
    url="${url:-https://umd.instructure.com}"
    sed -i.bak "s|^CANVAS_BASE_URL=.*|CANVAS_BASE_URL=${url}|" .env && rm -f .env.bak
    echo ".env created with CANVAS_BASE_URL=${url}"
    echo "(add ANTHROPIC_API_KEY to .env later to enable draft generation)"
fi

echo
echo "Setup complete. Now run:"
echo "  python main.py login          # Chrome opens -> log in -> press Enter here"
echo "  python main.py session-debug  # quick check that it sees your courses"
echo "  python main.py all --dry-run  # the whole detection run, downloads nothing"
