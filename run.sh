#!/usr/bin/env bash
# Sets up (first run only) and launches Lineup Lab locally.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Setting up virtual environment (first run only)..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q --upgrade pip
else
  source .venv/bin/activate
fi

# always sync deps (fast no-op when nothing changed) so a newly added
# package in requirements.txt doesn't silently go missing on an existing venv
pip install -q -r requirements.txt

echo "Starting Lineup Lab on http://localhost:8420"
uvicorn server:app --host 0.0.0.0 --port 8420
