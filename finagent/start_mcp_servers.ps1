# ==============================================
# Start ProspektLab v3 MCP Servers
# ==============================================
# This script starts only the v3 two-server topology:
#   - discovery_server.py on :8003
#   - quant_server.py on :8005

$ErrorActionPreference = "Stop"

Write-Host "Starting ProspektLab v3 MCP Servers..." -ForegroundColor Cyan

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv-prospektlab311b\Scripts\python.exe"
if (!(Test-Path $python)) {
    $python = "python"
}

Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "cd '$repoRoot'; & '$python' -m finagent.tools.mcp_servers.quant_server"
Start-Sleep -Seconds 1

Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "cd '$repoRoot'; & '$python' -m finagent.tools.mcp_servers.discovery_server"

Write-Host "`nQuant (:8005) and Discovery (:8003) servers are starting." -ForegroundColor Green
Write-Host "You can now run the main API server." -ForegroundColor Yellow
