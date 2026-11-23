# ==============================================================================
# Lathe Agent Quick Installer for Windows PowerShell
# Installs uv (if missing), installs lathe-agent tool, and runs `lathe doctor`.
# Usage:
#   irm https://raw.githubusercontent.com/adityasurse/lathe/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host @"
  _          _   _          
 | |   __ _ | |_| |__   ___ 
 | |  / _` || __| '_ \ / _ \
 | | | (_| || |_| | | |  __/
 |_|  \__,_| \__|_| |_|\___|
 Autonomous Terminal AI Agent
"@ -ForegroundColor Cyan

# 1. Ensure User local bin path is available
$UserBin = Join-Path $env:USERPROFILE ".local\bin"
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ($env:Path -notlike "*$UserBin*") {
    $env:Path = "$UserBin;$CargoBin;$env:Path"
}

# 2. Check or install uv
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "`nuv not found. Installing Astral uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$UserBin;$CargoBin;$env:Path"
}

if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Failed to install or locate 'uv'. Please install manually from https://astral.sh/uv" -ForegroundColor Red
    exit 1
}

$uvVersion = (uv --version)
Write-Host "✓ uv is ready ($uvVersion)" -ForegroundColor Green

# 3. Install or update lathe-agent via uv tool
Write-Host "`nInstalling lathe-agent via 'uv tool install'..." -ForegroundColor Cyan

if ((Test-Path "pyproject.toml") -and (Select-String -Path "pyproject.toml" -Pattern 'name = "lathe-agent"' -Quiet)) {
    Write-Host "Detected local lathe-agent repository. Installing local build..." -ForegroundColor Yellow
    uv tool install . --force
} else {
    uv tool install lathe-agent --force
}

# Refresh path
$env:Path = "$UserBin;$env:Path"

Write-Host "`n✓ Lathe installed successfully!" -ForegroundColor Green
Write-Host "`nRunning 'lathe doctor' to verify local runtimes and models...`n" -ForegroundColor Cyan

# 4. Run diagnostics
try {
    lathe doctor
} catch {
    Write-Host "Note: Could not run 'lathe doctor' automatically. Try opening a new terminal window." -ForegroundColor Yellow
}

Write-Host "`n🚀 All set! Get started by running:" -ForegroundColor Green
Write-Host "   lathe               # Launch interactive REPL session" -ForegroundColor White
Write-Host "   lathe `"<task>`"      # Run autonomous agent on a specific task" -ForegroundColor White
Write-Host "   lathe --dual `"<task>`"# Run planner + coder dual-model mode" -ForegroundColor White
Write-Host "   lathe --help        # View all CLI commands and options`n" -ForegroundColor White
