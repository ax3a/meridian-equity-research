<#
.SYNOPSIS
    Stop and remove the Meridian docker compose stack (Windows / PowerShell 5.1+).

.DESCRIPTION
    Mirrors `make docker-down` in the root Makefile - keep the two in sync. Tears down every
    service, including the ones in the `full` profile; named volumes (e.g. the Postgres data
    volume) are kept unless you pass -Volumes.

.PARAMETER Volumes
    Also remove named volumes (drops the Postgres data volume - use with care).
#>

param(
    [switch]$Volumes
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $RepoRoot
try {
    $composeArgs = @("compose", "--profile", "full", "down")
    if ($Volumes) {
        $composeArgs += "--volumes"
    }
    Write-Host "==> docker $($composeArgs -join ' ')" -ForegroundColor Cyan
    docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host "Stack stopped." -ForegroundColor Green
