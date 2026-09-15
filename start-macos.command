#!/bin/bash
set -e
cd "$(dirname "$0")"
fail() {
  echo "$1"
  read -r -p 'Press Return to close...' || true
  exit 1
}
if [ ! -x .venv/bin/python ]; then
  command -v python3 >/dev/null 2>&1 || fail 'Install Python 3.11 from https://www.python.org/downloads/macos/'
  python3 -m venv .venv || fail 'Could not create the Python environment.'
fi
if ! .venv/bin/python -c 'import pymupdf, pypdf, fontTools, pathops, certifi' >/dev/null 2>&1; then
  if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip --upgrade || fail 'Could not install pip. Repair your Python installation and retry.'
  fi
  .venv/bin/python -m pip install -r requirements.txt || fail 'Setup failed. Check your network and retry.'
fi
.venv/bin/python server.py || fail 'editPDFbyAI could not start. See the error above.'
