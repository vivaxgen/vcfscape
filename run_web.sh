#!/usr/bin/env bash
# ==============================================================================
# Helper script to launch VCFscape - VCF inspector part of vivaxGEN Project (Web)
# Works out-of-the-box on local Linux, macOS, or WSL systems.
# ==============================================================================

set -e

# 1. If vcfscape-web command is available in PATH
if command -v vcfscape-web &> /dev/null; then
    exec vcfscape-web "$@"
fi

# 2. If python3 is available in local checkout
if command -v python3 &> /dev/null; then
    if [ -f "src/vcfscape/web_server.py" ]; then
        exec env PYTHONPATH=src python3 -m vcfscape.web_server "$@"
    fi
fi

# 3. If npm/Node.js is available
if command -v npm &> /dev/null; then
    if [ ! -d "node_modules" ]; then
        echo "Installing npm packages..."
        npm install
    fi
    exec npm run dev -- "$@"
fi

echo "Error: Neither Python 3 nor Node.js was found to launch the web simulator."
exit 1
