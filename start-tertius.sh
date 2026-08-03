#!/usr/bin/env bash
# Tertius - local, offline transcription.
#
# All of the real work - building the virtual environment, installing
# dependencies, deciding what to do about an already-running server - lives in
# app/src/tertius/launcher.py, so Windows, macOS and Linux share one copy of it.
# This script only has to find a Python and hand over.
#
#   chmod +x start-tertius.sh && ./start-tertius.sh

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
launcher="$here/app/src/tertius/launcher.py"

python=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        # 3.9 is the floor declared in pyproject.toml.
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            python="$candidate"
            break
        fi
    fi
done

if [ -z "$python" ]; then
    echo
    echo "  ERROR: Python 3.9 or newer was not found on PATH."
    echo
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-tk"
    echo "  Fedora:         sudo dnf install python3 python3-tkinter"
    echo "  macOS:          brew install python-tk"
    echo
    exit 1
fi

exec "$python" "$launcher" "$@"
