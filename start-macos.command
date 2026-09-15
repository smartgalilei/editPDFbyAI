#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo 'Install Python 3.11 from https://www.python.org/downloads/macos/'
    read -r -p 'Press Return to close...'
    exit 1
  fi
  python3 -m venv .venv
fi
if ! .venv/bin/python -m pip install -r requirements.txt; then
  read -r -p 'Setup failed. Check your network. Press Return to close...'
  exit 1
fi
exec .venv/bin/python server.py
