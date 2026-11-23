#!/usr/bin/env bash
# ==============================================================================
# Lathe Agent Quick Installer for Linux and macOS
# Installs uv (if missing), installs lathe-agent tool, and runs `lathe doctor`.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/adityasurse/lathe/main/install.sh | bash
# ==============================================================================

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}"
echo "  _          _   _          "
echo " | |   __ _ | |_| |__   ___ "
echo " | |  / _\` || __| '_ \ / _ \\"
echo " | | | (_| || |_| | | |  __/"
echo " |_|  \__,_| \__|_| |_|\___|"
echo " Autonomous Terminal AI Agent"
echo -e "${NC}"

# 1. Ensure PATH has common tool directories
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 2. Check or install Astral's uv
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${YELLOW}uv not found. Installing Astral uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to install or locate 'uv'. Please install manually from https://astral.sh/uv${NC}"
    exit 1
fi

echo -e "${GREEN}✓ uv is ready ($(uv --version))${NC}"

# 3. Install or update lathe-agent via uv tool
echo -e "\n${CYAN}Installing lathe-agent via 'uv tool install'...${NC}"

# If running within a cloned repository, install editable/local, otherwise install from PyPI
if [ -f "pyproject.toml" ] && grep -q 'name = "lathe-agent"' pyproject.toml 2>/dev/null; then
    echo -e "${YELLOW}Detected local lathe-agent repository. Installing local build...${NC}"
    uv tool install . --force
else
    uv tool install lathe-agent --force
fi

# Ensure tool bin path is exported in current session
export PATH="$HOME/.local/bin:$PATH"

if ! command -v lathe >/dev/null 2>&1; then
    echo -e "${YELLOW}Note: 'lathe' is installed in ~/.local/bin. Ensure ~/.local/bin is in your PATH:${NC}"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo -e "\n${GREEN}${BOLD}✓ Lathe installed successfully!${NC}"
echo -e "\n${CYAN}Running 'lathe doctor' to verify local runtimes and models...${NC}\n"

# 4. Run diagnostics
if command -v lathe >/dev/null 2>&1; then
    lathe doctor || true
else
    ~/.local/bin/lathe doctor || true
fi

echo -e "\n${GREEN}${BOLD}🚀 All set! Get started by running:${NC}"
echo -e "   ${BOLD}lathe${NC}               # Launch interactive REPL session"
echo -e "   ${BOLD}lathe \"<task>\"${NC}      # Run autonomous agent on a specific task"
echo -e "   ${BOLD}lathe --dual \"<task>\"${NC}# Run planner + coder dual-model mode"
echo -e "   ${BOLD}lathe --help${NC}        # View all CLI commands and options\n"
