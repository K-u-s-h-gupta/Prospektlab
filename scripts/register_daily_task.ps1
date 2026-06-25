# Register the ProspektLab daily publisher with Windows Task Scheduler.
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1

param(
    [string]$TaskName = "ProspektLab-Daily-Publisher",
    [string]$At = "06:30"
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = Join-Path $repo "scripts\run_daily_publisher.ps1"
$logDir = Join-Path $repo ".finagent\daily_runs"

if (-not (Test-Path $runner)) {
    throw "Daily publisher runner not found: $runner"
}
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$powerShell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $actionArgs -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -DontStopOnIdleEnd -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Run the ProspektLab daily publisher and write logs under .finagent\daily_runs." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'. Runs daily at $At local time." -ForegroundColor Green
Write-Host "Runner: $runner"
Write-Host "Logs: $logDir\task-*.log and $logDir\run-*.json"
Write-Host "Run on demand: Start-ScheduledTask -TaskName '$TaskName'"
