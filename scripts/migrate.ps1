<#
.SYNOPSIS
    Apply Alembic database migrations (Windows / PowerShell 5.1+).

.DESCRIPTION
    Runs `alembic upgrade head` from backend/ against whatever DATABASE_URL settings.py resolves
    (repo-root .env, then backend/.env, then the real environment). Requires Postgres to be
    reachable - see scripts\docker-up.ps1 -DepsOnly.

    Mirrors `make migrate` in the root Makefile - keep the two in sync.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

if (-not (Test-Path (Join-Path $RepoRoot ".env"))) {
    Write-Warning ".env not found at repo root - migrate will fall back to the default DATABASE_URL in Settings."
}

Write-Host "==> alembic upgrade head" -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "alembic upgrade head failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host "Migrations applied." -ForegroundColor Green
