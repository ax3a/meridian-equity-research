<#
.SYNOPSIS
    Run the Meridian evaluation harness (Windows / PowerShell 5.1+).

.DESCRIPTION
    Mirrors `make eval` in the root Makefile - keep the two in sync. The evaluation harness lives
    under backend/evals (see Task 14 of the implementation plan); this script no-ops with a clear
    message if it has not been added yet.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$EvalsDir = Join-Path $RepoRoot "evals"

if (-not (Test-Path $EvalsDir)) {
    Write-Host "evals/ does not exist yet (Task 14) - nothing to run."
    exit 0
}

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

Write-Host "==> python -m evals.run" -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & $VenvPython -m evals.run
    if ($LASTEXITCODE -ne 0) {
        throw "evaluation harness failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}
