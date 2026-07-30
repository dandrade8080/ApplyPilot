#!/usr/bin/env bash
# ApplyPilot - Quick Install (Linux / macOS)
# Downloads and installs ApplyPilot for local use.
#
# Usage: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "========================================"
echo "  ApplyPilot - Installer (Linux/macOS)"
echo "========================================"
echo ""

# ---- Check Python ----
echo "[1/4] Checking Python 3.11+..."
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "  ERROR: Python not found."
    echo "  Install Python 3.11+ from https://python.org"
    exit 1
fi
echo "  OK: $($PYTHON --version)"

# ---- Install ApplyPilot ----
echo "[2/4] Installing ApplyPilot..."
$PYTHON -m pip install applypilot

# ---- Install python-jobspy ----
echo "[3/4] Installing python-jobspy..."
$PYTHON -m pip install --no-deps python-jobspy
$PYTHON -m pip install pydantic tls-client requests markdownify regex

# ---- Run setup wizard ----
echo "[4/4] Starting setup wizard..."
echo ""
echo "Follow the interactive wizard:"
echo "  1. Choose your resume file (.txt or .pdf)"
echo "  2. Fill in your professional profile"
echo "  3. Define job titles and locations to search"
echo "  4. Configure scoring preferences"
echo "     (profession category, seniority, skills)"
echo "  5. Set up your LLM API key (optional)"
echo ""

applypilot init

echo ""
echo "========================================"
echo "  Installation complete!"
echo ""
echo "  Discover jobs:     applypilot run"
echo "  Check status:      applypilot status"
echo "  Web dashboard:     applypilot dashboard"
echo "  Help:              applypilot --help"
echo "========================================"
echo ""
