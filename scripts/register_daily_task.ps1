# Register the ProspektLab daily publisher with Windows Task Scheduler.
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1

$repo   = "D:\PROSPEKTLAB"
$python = "$repo\.venv-prospektlab311b\Scripts\python.exe"
$script = "$repo\scripts\daily_publisher.py"
$logDir = "$repo\.finagent\daily_runs"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$action  = New-ScheduledTaskAction -Execute $python -Argument $script -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 06:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
            -DontStopOnIdleEnd -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) `
            -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "ProspektLab-Daily-Publisher" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Run the ProspektLab daily publisher (15-20 strong articles per day)." `
    -Force | Out-Null

Write-Host "Registered scheduled task 'ProspektLab-Daily-Publisher'. Runs daily at 06:30 IST-equivalent local time." -ForegroundColor Green
Write-Host "Logs: $logDir\run-*.json"
Write-Host "Run on demand: Start-ScheduledTask -TaskName 'ProspektLab-Daily-Publisher'"
