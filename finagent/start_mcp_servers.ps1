# ==============================================
# Start All FinAgent MCP Servers
# ==============================================
# This script starts all 5 MCP servers in separate windows.

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Starting FinAgent MCP Servers..." -ForegroundColor Cyan

$basePath = "C:\Users\kusha\OneDrive\डेस्कटॉप\PROSPEKTLAB\finagent"

# Start each MCP server in a new PowerShell window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$basePath'; python -m finagent.tools.mcp_servers.nse_server"
Start-Sleep -Seconds 1

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$basePath'; python -m finagent.tools.mcp_servers.fundamentals_server"
Start-Sleep -Seconds 1

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$basePath'; python -m finagent.tools.mcp_servers.research_server"
Start-Sleep -Seconds 1

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$basePath'; python -m finagent.tools.mcp_servers.docs_server"
Start-Sleep -Seconds 1

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$basePath'; python -m finagent.tools.mcp_servers.mcp_valuation"

Write-Host "`nAll MCP servers are starting in separate windows." -ForegroundColor Green
Write-Host "You can now run the main API server." -ForegroundColor Yellow
