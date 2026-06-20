<#
.SYNOPSIS
    ProspektLab IKG APScheduler launcher.
.DESCRIPTION
    Starts the official-source ingestion scheduler as a separate process from
    the FastAPI gateway. The scheduler reads backend/finagent/.env automatically.
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

function Test-PythonCandidate {
    param(
        [string]$PythonPath
    )

    if (-not (Test-Path $PythonPath)) {
        return $false
    }

    $venvRoot = Split-Path -Parent (Split-Path -Parent $PythonPath)
    $pyvenvCfg = Join-Path $venvRoot "pyvenv.cfg"
    if (-not (Test-Path $pyvenvCfg)) {
        return $false
    }

    & $PythonPath -c "import finagent; import finagent.ikg.pipeline.scheduler" *> $null
    return ($LASTEXITCODE -eq 0)
}

$Python = $null
foreach ($candidate in $CandidateVenvs) {
    if (Test-PythonCandidate -PythonPath $candidate) {
        $Python = $candidate
        break
    }
}

if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    python -c "import finagent; import finagent.ikg.pipeline.scheduler" *> $null
    if ($LASTEXITCODE -eq 0) {
        $Python = "python"
    }
}

if (-not $Python) {
    Write-Host "[ERROR] No working Python runtime found for IKG scheduler startup." -ForegroundColor Red
    Write-Host "Expected a venv with pyvenv.cfg and installed backend deps." -ForegroundColor Red
    exit 1
}

Write-Host "Starting ProspektLab IKG scheduler..." -ForegroundColor Cyan
Write-Host "Python: $Python" -ForegroundColor DarkGray

$Args = @("-m", "finagent.ikg.pipeline.scheduler")
if ($Once) {
    $Args += "--once"
}

& $Python @Args
