<#
.SYNOPSIS
    Start the Meridian docker compose stack (Windows / PowerShell 5.1+).

.DESCRIPTION
    By default brings up the full containerized stack (db, redis, backend, frontend) via the
    `full` compose profile, building images as needed. Pass -DepsOnly to start just Postgres and
    Redis, which is the usual local-dev setup when you run the backend/frontend natively with
    scripts\dev.ps1 against them.

    Mirrors `make docker-up` / `make docker-up-deps` in the root Makefile - keep them in sync.

.PARAMETER DepsOnly
    Start only the `db` and `redis` services (no build, no backend/frontend containers).

.EXAMPLE
    scripts\docker-up.ps1
    Builds and starts the full stack: http://localhost:3000 (frontend), http://localhost:8000 (backend).

.EXAMPLE
    scripts\docker-up.ps1 -DepsOnly
    Starts only Postgres (localhost:5432) and Redis (localhost:6379).
#>

param(
    [switch]$DepsOnly
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path $EnvFile)) {
    Write-Host "==> Creating .env from .env.example"
    Copy-Item $EnvExample $EnvFile
}

Push-Location $RepoRoot
try {
    if ($DepsOnly) {
        Write-Host "==> docker compose up -d db redis" -ForegroundColor Cyan
        docker compose up -d db redis
    } else {
        Write-Host "==> docker compose --profile full up -d --build" -ForegroundColor Cyan
        docker compose --profile full up -d --build
    }
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

if ($DepsOnly) {
    Write-Host "Postgres (5432) and Redis (6379) are up." -ForegroundColor Green
} else {
    Write-Host "Stack is up: frontend http://localhost:3000, backend http://localhost:8000" -ForegroundColor Green
}
