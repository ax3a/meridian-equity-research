<#
.SYNOPSIS
    Run the Meridian test suites (Windows / PowerShell 5.1+): backend pytest, then frontend vitest.

.DESCRIPTION
    Mirrors `make test` in the root Makefile - keep the two in sync. Integration tests that need
    Postgres/Redis are marked `@pytest.mark.integration` and skip cleanly when those services are
    unreachable; start them first with scripts\docker-up.ps1 -DepsOnly to exercise them.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

Write-Host "==> Backend: pytest -q" -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & $VenvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Backend tests failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host "==> Frontend: npm run test" -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    npm run test
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend tests failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host "All tests passed." -ForegroundColor Green
