#!/usr/bin/env bash
# ==============================================================================
# Helper script to launch VCFscape - VCF inspector part of vivaxGEN Project (Textual TUI)
# ==============================================================================

set -e

if command -v vcfscape &> /dev/null; then
    exec vcfscape --demo "$@"
fi

if command -v python3 &> /dev/null; then
    exec env PYTHONPATH=src python3 -m vcfscape.cli --demo "$@"
fi

echo "Error: Python 3 not found."
exit 1
