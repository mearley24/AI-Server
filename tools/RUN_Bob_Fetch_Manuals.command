#!/bin/bash
set -euo pipefail
cd "$HOME/AI-Server"
source "$HOME/AI-Server/.venv/bin/activate"
python "$HOME/AI-Server/tools/bob_fetch_manuals.py"
