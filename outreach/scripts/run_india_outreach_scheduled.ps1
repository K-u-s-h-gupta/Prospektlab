$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "outreach\state\scheduler"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutPath = Join-Path $logDir ("batch-" + $stamp + ".out.log")
$stderrPath = Join-Path $logDir ("batch-" + $stamp + ".err.log")

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "outreach\scripts\run_supabase_outreach_batch.py"
$configPath = Join-Path $repoRoot "outreach\config.local.json"

$arguments = @(
    $scriptPath,
    "--config", $configPath,
    "--owner-email", "aryan@prospektlab.com",
    "--campaign-name", "IndiaFinanceOutreach",
    "--max-send", "30",
    "--delay-seconds", "0",
    "--send"
)

Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $arguments `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -Wait `
    -NoNewWindow
