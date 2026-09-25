<#
.SYNOPSIS
    Lint the Meridian codebase (Windows / PowerShell 5.1+): ruff (backend), eslint + tsc (frontend).

.DESCRIPTION
    Mirrors `make lint` in the root Makefile - keep the two in sync. Does not modify any files;
    use scripts\format.ps1 to auto-fix what can be auto-fixed.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

Write-Host "==> Backend: ruff check" -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & $VenvPython -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw "ruff check failed (exit code $LASTEXITCODE)." }

    Write-Host "==> Backend: ruff format --check" -ForegroundColor Cyan
    & $VenvPython -m ruff format --check src tests
    if ($LASTEXITCODE -ne 0) { throw "ruff format --check failed (exit code $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

Write-Host "==> Frontend: eslint" -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw "eslint failed (exit code $LASTEXITCODE)." }

    Write-Host "==> Frontend: tsc --noEmit" -ForegroundColor Cyan
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "tsc --noEmit failed (exit code $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

Write-Host "Lint clean." -ForegroundColor Green
