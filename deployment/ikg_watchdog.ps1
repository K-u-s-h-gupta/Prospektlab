param(
  [string]$ComposeFile = "deployment/docker-compose.ikg.yml",
  [int]$WorkerReplicas = 2,
  [string]$LogDir = "pipeline_logs"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$resolvedCompose = Join-Path $projectDir $ComposeFile
$resolvedLogDir = Join-Path $projectDir $LogDir
New-Item -ItemType Directory -Force -Path $resolvedLogDir | Out-Null
$logFile = Join-Path $resolvedLogDir ("ikg_watchdog_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Write-Log {
  param([string]$Message)
  $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
  Add-Content -Path $logFile -Value $line
  Write-Host $line
}

function Invoke-Compose {
  param([string[]]$Args)
  & docker compose -f $resolvedCompose @Args
}

function Get-HealthStatus {
  $json = Invoke-Compose @("exec", "-T", "scheduler", "python", "-m", "finagent.ikg.pipeline.orchestrator", "--phase", "health") 2>$null
  if (-not $json) { return "unknown" }
  try {
    $parsed = $json | ConvertFrom-Json
    return [string]$parsed.status
  } catch {
    return "unknown"
  }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Log "docker CLI is not available"
  exit 1
}

Write-Log "Ensuring IKG compose stack is running"
Invoke-Compose @("up", "-d", "--scale", "celery-worker=$WorkerReplicas") | Out-Null

$status = Get-HealthStatus
Write-Log "Health status: $status"

if ($status -eq "error" -or $status -eq "unknown") {
  Write-Log "Restarting scheduler and workers after unhealthy probe"
  Invoke-Compose @("restart", "scheduler", "celery-worker") | Out-Null
  Start-Sleep -Seconds 10
  $status = Get-HealthStatus
  Write-Log "Health status after restart: $status"
}

if ($status -eq "error") {
  exit 2
}
