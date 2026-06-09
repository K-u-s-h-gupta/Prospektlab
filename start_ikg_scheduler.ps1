<#
.SYNOPSIS
    ProspektLab IKG APScheduler launcher.
.DESCRIPTION
    Starts the official-source ingestion scheduler as a separate process from
    the FastAPI gateway. The scheduler reads finagent/.env automatically.
.EXAMPLE
    .\start_ikg_scheduler.ps1
    .\start_ikg_scheduler.ps1 -Once
#>

param(
    [switch]$Once
)

$ErrorActionPreference = "Stop"

$CandidateVenvs = @(
    "D:\PROSPEKTLAB\.venv\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-finagent\Scripts\python.exe",
    "D:\PROSPEKTLAB\.venv-finagent-311\Scripts\python.exe"
)

$Python = ($CandidateVenvs | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Python) {
    $Python = "python"
}

Write-Host "Starting ProspektLab IKG scheduler..." -ForegroundColor Cyan
Write-Host "Python: $Python" -ForegroundColor DarkGray

$Args = @("-m", "finagent.ikg.pipeline.scheduler")
if ($Once) {
    $Args += "--once"
}

& $Python @Args
