#!/bin/bash
source "$HOME/AI-Server/.venv/bin/activate"
python "$HOME/AI-Server/orchestrator/core/bob_orchestrator.py" "$@"
