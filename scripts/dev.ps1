<#
.SYNOPSIS
    Run the Meridian backend and frontend dev servers together (Windows / PowerShell 5.1+).

.DESCRIPTION
    Starts `uvicorn --reload` for the backend (http://localhost:8000) and `npm run dev` for the
    frontend (http://localhost:3000) as sibling child processes sharing this console. Press
    Ctrl+C to stop both.

    Requires scripts\setup.ps1 to have been run first (backend venv + npm install), and
    Postgres/Redis to be reachable (see scripts\docker-up.ps1 -DepsOnly, or your own local
    install) — the backend will fail to start otherwise.

    Mirrors `make dev` in the root Makefile - keep the two in sync.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Backend venv not found at $VenvPython. Run scripts\setup.ps1 first."
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npmCommand) {
    throw "npm was not found on PATH. Install Node.js first."
}

Write-Host "==> Starting backend  (http://localhost:8000, --reload)"
Write-Host "==> Starting frontend (http://localhost:3000)"
Write-Host "    Press Ctrl+C to stop both."

$backendArgs = @(
    "-m", "uvicorn", "meridian.api.app:create_app", "--factory", "--reload",
    "--host", "0.0.0.0", "--port", "8000"
)
$backendProc = Start-Process -FilePath $VenvPython -ArgumentList $backendArgs `
    -WorkingDirectory $BackendDir -NoNewWindow -PassThru

$frontendProc = Start-Process -FilePath $npmCommand.Source -ArgumentList @("run", "dev") `
    -WorkingDirectory $FrontendDir -NoNewWindow -PassThru

try {
    Wait-Process -Id $backendProc.Id, $frontendProc.Id
}
finally {
    Write-Host ""
    Write-Host "==> Stopping dev servers..."
    foreach ($proc in @($backendProc, $frontendProc)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
