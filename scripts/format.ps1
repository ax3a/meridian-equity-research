<#
.SYNOPSIS
    Auto-format the Meridian codebase (Windows / PowerShell 5.1+): ruff format + ruff --fix
    (backend), eslint --fix (frontend).

.DESCRIPTION
    Mirrors `make format` in the root Makefile - keep the two in sync.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

Write-Host "==> Backend: ruff format" -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & $VenvPython -m ruff format src tests
    if ($LASTEXITCODE -ne 0) { throw "ruff format failed (exit code $LASTEXITCODE)." }

    Write-Host "==> Backend: ruff check --fix" -ForegroundColor Cyan
    & $VenvPython -m ruff check --fix src tests
    if ($LASTEXITCODE -ne 0) { throw "ruff check --fix failed (exit code $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

Write-Host "==> Frontend: eslint --fix" -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    npx eslint . --fix
    if ($LASTEXITCODE -ne 0) { throw "eslint --fix failed (exit code $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

Write-Host "Formatting complete." -ForegroundColor Green
