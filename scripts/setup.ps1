<#
.SYNOPSIS
    Meridian developer setup (Windows / PowerShell 5.1+).

.DESCRIPTION
    Creates the backend virtualenv, installs the backend package (with dev/embeddings/otel
    extras), installs frontend npm dependencies, and copies .env.example -> .env (and the
    frontend's .env.local.example -> .env.local) if they do not already exist.

    Mirrors `make setup` in the root Makefile - keep the two in sync.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    Write-Host "> $FilePath $($ArgumentList -join ' ')  (in $WorkingDirectory)" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code $LASTEXITCODE : $FilePath $($ArgumentList -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-PythonVersionTag {
    # Prints "3.12" style major.minor for whatever interpreter $FilePath/$ArgPrefix resolves to,
    # or $null if it can't be run at all. Never throws.
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgPrefix = @()
    )
    try {
        $probeArgs = $ArgPrefix + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
        $out = & $FilePath @probeArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            return ($out | Select-Object -Last 1).ToString().Trim()
        }
    } catch {
        # Interpreter genuinely not runnable (missing, wrong arch, etc.) - treat as not found.
    }
    return $null
}

function Resolve-Python312 {
    # This project targets Python >= 3.12 (backend/pyproject.toml). A bare `python` on PATH is
    # not reliable on Windows: PATH order varies by shell/session (Miniconda/Anaconda often
    # shadows python.org installs), and silently building the venv against the wrong interpreter
    # produces confusing binary-mismatch failures later (e.g. compiled deps like pydantic-core
    # failing to import). Prefer the Python Launcher (`py -3.12`), which asks for that version
    # explicitly regardless of PATH order, and verify whatever we do pick before using it.
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $tag = Get-PythonVersionTag -FilePath "py" -ArgPrefix @("-3.12")
        if ($tag -eq "3.12") {
            return [pscustomobject]@{ FilePath = "py"; ArgPrefix = @("-3.12") }
        }
    }

    foreach ($candidate in @("python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $tag = Get-PythonVersionTag -FilePath $candidate -ArgPrefix @()
        if ($tag -eq "3.12") {
            return [pscustomobject]@{ FilePath = $candidate; ArgPrefix = @() }
        }
    }

    throw ("Could not find a Python 3.12 interpreter (checked 'py -3.12', 'python', 'python3'). " +
        "Install Python 3.12 from https://www.python.org/downloads/ and re-run this script. " +
        "If you have multiple Pythons installed (e.g. Anaconda/Miniconda), installing the " +
        "Windows Python Launcher lets this script find the right one via 'py -3.12' regardless " +
        "of PATH order.")
}

Write-Host "==> Repo root: $RepoRoot"

# --- .env files --------------------------------------------------------------------------
$envFile = Join-Path $RepoRoot ".env"
$envExample = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Write-Host "==> Creating .env from .env.example"
    Copy-Item $envExample $envFile
} else {
    Write-Host "==> .env already exists, leaving it alone"
}

$feEnvFile = Join-Path $FrontendDir ".env.local"
$feEnvExample = Join-Path $FrontendDir ".env.local.example"
if (-not (Test-Path $feEnvFile)) {
    Write-Host "==> Creating frontend/.env.local from .env.local.example"
    Copy-Item $feEnvExample $feEnvFile
} else {
    Write-Host "==> frontend/.env.local already exists, leaving it alone"
}

# --- Backend venv --------------------------------------------------------------------------
$venvDir = Join-Path $BackendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

$existingTag = $null
if (Test-Path $venvPython) {
    $existingTag = Get-PythonVersionTag -FilePath $venvPython -ArgPrefix @()
}

if ($existingTag -eq "3.12") {
    Write-Host "==> Existing venv at $venvDir is already Python 3.12 - keeping it"
} else {
    if (Test-Path $venvDir) {
        $found = if ($existingTag) { $existingTag } else { "unknown/broken" }
        Write-Host "==> Existing venv at $venvDir is Python $found, not 3.12 - recreating it"
        Remove-Item -Recurse -Force $venvDir
    }
    $py = Resolve-Python312
    Write-Host "==> Creating backend virtualenv at $venvDir using: $($py.FilePath) $($py.ArgPrefix -join ' ')"
    Invoke-Native -FilePath $py.FilePath -ArgumentList ($py.ArgPrefix + @("-m", "venv", $venvDir)) -WorkingDirectory $RepoRoot
}

Write-Host "==> Upgrading pip"
Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") -WorkingDirectory $RepoRoot

Write-Host "==> Installing backend package (.[dev,embeddings,otel])"
Invoke-Native -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "-e", ".[dev,embeddings,otel]") -WorkingDirectory $BackendDir

# --- Frontend npm install --------------------------------------------------------------------------
Write-Host "==> Installing frontend dependencies (npm install)"
Invoke-Native -FilePath "npm" -ArgumentList @("install") -WorkingDirectory $FrontendDir

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  Backend venv:  $venvPython"
Write-Host "  Next steps:    edit .env (API keys are optional - the platform runs offline without them)"
Write-Host "                 scripts\docker-up.ps1 -DepsOnly   # start Postgres + Redis"
Write-Host "                 scripts\migrate.ps1                # apply database migrations"
Write-Host "                 scripts\dev.ps1                    # run backend + frontend"
