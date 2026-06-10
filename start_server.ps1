<#
.SYNOPSIS
    ProspektLab Server Launcher (PowerShell)
    Always uses the correct virtual environment Python interpreter.
.DESCRIPTION
    This script prefers the project's full backend venv (.venv) so the
    gateway starts with the complete dependency set. If that environment is
    unavailable, it falls back to the older project venvs.
.EXAMPLE
    .\start_server.ps1
    .\start_server.ps1 --port 8080
#>

param(
    [string[]]$UvicornArgs
)

$ErrorActionPreference = "Stop"

$CandidateVenvs = @(
    "D:\PROSPEKTLAB\.venv\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-finagent\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-finagent-311\Scripts\python.exe"
)

$VenvPython = $CandidateVenvs | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $VenvPython) {
    Write-Host "[ERROR] Virtual environment Python not found at:" -ForegroundColor Red
    Write-Host $VenvPython -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please create/restore one of the project venvs or update the path in this script." -ForegroundColor Red
    exit 1
}

Write-Host "Starting ProspektLab gateway using venv Python..." -ForegroundColor Cyan
Write-Host "Python: $VenvPython" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython -m uvicorn finagent.gateway.run:app --reload @UvicornArgs
