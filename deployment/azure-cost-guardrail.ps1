# Guardrail script for focused Azure monitoring scope.
# Intended to be invoked manually or from an alert action when monthly spend is near hard cap.

param(
    [string]$ResourceGroup = "prospektlab-monitoring-rg",
    [string]$WorkspaceName = "prospektlab-monitoring",
    [int]$HardCapMonthlyUsd = 120,
    [double]$CurrentMonthSpendUsd = 0,
    [double]$ThrottleQuotaGb = 2.0,
    [switch]$ThrottleNow
)

$ErrorActionPreference = "Stop"

function Invoke-AzCli {
    param([string[]]$Args)
    & az @Args
    if ($LASTEXITCODE -ne 0) {
        throw ("Azure CLI command failed: az " + ($Args -join " "))
    }
}

Invoke-AzCli -Args @("account", "show", "--output", "none")

$shouldThrottle = $ThrottleNow -or ($CurrentMonthSpendUsd -ge $HardCapMonthlyUsd)
if (-not $shouldThrottle) {
    Write-Host "No action taken. Current spend ($CurrentMonthSpendUsd) is below hard cap ($HardCapMonthlyUsd)." -ForegroundColor Green
    return
}

Write-Host "Applying guardrail: lowering Log Analytics daily quota to $ThrottleQuotaGb GB." -ForegroundColor Yellow
Invoke-AzCli -Args @(
    "monitor", "log-analytics", "workspace", "update",
    "--resource-group", $ResourceGroup,
    "--workspace-name", $WorkspaceName,
    "--quota", "$ThrottleQuotaGb"
)

Write-Host "Guardrail applied successfully." -ForegroundColor Green
