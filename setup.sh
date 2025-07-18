#!/usr/bin/env bash
# --------------------------------------------------------------------------------------------------------------------
# Bootstrap script for Redis vs Dynamo benchmark host
# Tested on Amazon Linux 2023 (kernel 6.x) but works on AL2 with yum → dnf substitution.
# --------------------------------------------------------------------------------------------------------------------
set -euo pipefail

# ---- CONFIGURABLE VARIABLES ----------------------------------------------------------------------------------------
PYTHON="$(command -v python3 || command -v python)"         # auto-detect system python
# --------------------------------------------------------------------------------------------------------------------

echo "🛠  Updating system packages ..."
sudo dnf -y update
sudo dnf -y install git gcc gcc-c++ make curl libffi-devel openssl-devel

echo "🐍  Upgrading pip & installing pipx ..."
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install --upgrade pipx
# Ensure ~/.local/bin is on PATH in this session
export PATH="$HOME/.local/bin:$PATH"
pipx ensurepath || true   # idempotent

echo "⚡  Installing uv (fast dependency resolver from Astral) ..."
pipx install uv --force

echo "📍  Working in current directory (repo already cloned) ..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔗  Syncing dependencies and creating virtual environment ..."
# uv sync automatically creates .venv, installs Python if needed, and installs all dependencies
uv sync

echo "✅  Environment ready!"
echo "Run your benchmarks, e.g.:"
echo "    uv run python benchmark.py --db redis  --task write"
echo "    uv run python benchmark.py --db redis  --task read"
echo "    uv run python benchmark.py --db dynamo --task write"
echo "    uv run python benchmark.py --db dynamo --task read"
echo ""
