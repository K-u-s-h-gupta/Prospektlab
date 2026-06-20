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

    & $PythonPath -c "import uvicorn; import finagent" *> $null
    return ($LASTEXITCODE -eq 0)
}

$VenvPython = $null
foreach ($candidate in $CandidateVenvs) {
    if (Test-PythonCandidate -PythonPath $candidate) {
        $VenvPython = $candidate
        break
    }
}

if (-not $VenvPython) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        python -c "import uvicorn; import finagent" *> $null
        if ($LASTEXITCODE -eq 0) {
            $VenvPython = "python"
        }
    }
}

if (-not $VenvPython) {
    Write-Host "[ERROR] No working Python runtime found for backend startup." -ForegroundColor Red
    Write-Host ""
    Write-Host "Expected a venv with pyvenv.cfg and installed backend deps (uvicorn + finagent)." -ForegroundColor Red
    exit 1
}

Write-Host "Starting ProspektLab gateway using venv Python..." -ForegroundColor Cyan
Write-Host "Python: $VenvPython" -ForegroundColor DarkGray
Write-Host ""

& $VenvPython -m uvicorn finagent.gateway.run:app --reload @UvicornArgs
