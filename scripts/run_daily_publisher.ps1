<#
.SYNOPSIS
    Runs the ProspektLab daily publisher and writes a durable task log.
#>

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Script = Join-Path $Repo "scripts\daily_publisher.py"
$LogDir = Join-Path $Repo ".finagent\daily_runs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$CandidatePythons = @(
    (Join-Path $Repo ".venv\Scripts\python.exe"),
    (Join-Path $Repo ".venv-prospektlab311b\Scripts\python.exe"),
    (Join-Path $Repo ".venv-finagent-311\Scripts\python.exe"),
    (Join-Path $Repo ".venv-finagent\Scripts\python.exe")
)

$Python = $null
foreach ($candidate in $CandidatePythons) {
    if (Test-Path $candidate) {
        $Python = $candidate
        break
    }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Python = "python"
}
if (-not $Python) {
    throw "No Python runtime found for daily publisher."
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "task-$Stamp.log"
"== ProspektLab daily publisher task ==" | Out-File -FilePath $LogPath -Encoding utf8
"Started: $(Get-Date -Format o)" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"Repo: $Repo" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"Python: $Python" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"Script: $Script" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"" | Out-File -FilePath $LogPath -Encoding utf8 -Append

Push-Location $Repo
try {
    & $Python $Script *>> $LogPath
    $ExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
}
finally {
    Pop-Location
}

"" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"Finished: $(Get-Date -Format o)" | Out-File -FilePath $LogPath -Encoding utf8 -Append
"ExitCode: $ExitCode" | Out-File -FilePath $LogPath -Encoding utf8 -Append
exit $ExitCode
