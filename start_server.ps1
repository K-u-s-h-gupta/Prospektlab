<#
.SYNOPSIS
    ProspektLab Server Launcher (PowerShell)
    Always uses the correct virtual environment Python interpreter.
.DESCRIPTION
    This script forces the use of the project's dedicated venv
    (.venv-prospektlab311b) so that all dependencies (Docling, Pandas,
    OpenAI, matplotlib, etc.) are found correctly.
.EXAMPLE
    .\start_server.ps1
    .\start_server.ps1 --port 8080
#>

param(
    [string[]]$UvicornArgs
)

$ErrorActionPreference = "Stop"

$VenvPython = "D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment Python not found at:" -ForegroundColor Red
    Write-Host $VenvPython -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please create/restore the venv or update the path in this script." -ForegroundColor Red
    exit 1
}

Write-Host "Starting ProspektLab gateway using venv Python..." -ForegroundColor Cyan
Write-Host "Python: $VenvPython" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython -m uvicorn finagent.gateway.run:app --reload @UvicornArgs
