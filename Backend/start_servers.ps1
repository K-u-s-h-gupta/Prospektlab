# ORACLE FIOS - Start All MCP Servers
# =====================================
# Run this script once to bring up all 5 MCP servers in background jobs.
# Usage: .\start_servers.ps1
# Stop:  .\stop_servers.ps1

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  ORACLE FIOS - Starting MCP Servers  " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Kill anything already on these ports
@(8001, 8002, 8003, 8004, 8005) | ForEach-Object {
    $port = $_
    $pids = netstat -ano | Select-String ":$port " | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Sort-Object -Unique | Where-Object { $_ -match '^\d+$' }
    foreach ($p in $pids) {
        try { taskkill /PID $p /F 2>$null | Out-Null } catch {}
    }
}

Start-Sleep -Milliseconds 500

# Start each server as a detached background process
$servers = @(
    @{ Name = "NSE Market Data  "; Module = "mcp_servers.nse_server";          Port = 8001; Color = "Green"   },
    @{ Name = "Fundamentals     "; Module = "mcp_servers.fundamentals_server";  Port = 8002; Color = "Yellow"  },
    @{ Name = "Research & News  "; Module = "mcp_servers.research_server";      Port = 8003; Color = "Magenta" },
    @{ Name = "Document Pipeline"; Module = "mcp_servers.docs_server";          Port = 8004; Color = "Blue"    },
    @{ Name = "Valuation Engine "; Module = "mcp_servers.mcp_valuation";        Port = 8005; Color = "Cyan"    }
)

$pythonPath = Join-Path $PWD.Path ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

$processIds = @()
foreach ($s in $servers) {
    $proc = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("-m", $s.Module) `
        -WorkingDirectory $PWD.Path `
        -WindowStyle Hidden `
        -PassThru

    $processIds += [pscustomobject]@{
        Name = $s.Name.Trim()
        Port = $s.Port
        Module = $s.Module
        PID = $proc.Id
    }
    Write-Host "  [STARTED] " -ForegroundColor $s.Color -NoNewline
    Write-Host "$($s.Name)  ->  http://localhost:$($s.Port)/mcp"
}

Write-Host ""
Write-Host "All 5 servers are starting..." -ForegroundColor Cyan
Write-Host "Waiting 3 seconds for them to bind..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# Quick health check
Write-Host ""
Write-Host "Health Check:" -ForegroundColor Cyan
foreach ($s in $servers) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$($s.Port)/health" -TimeoutSec 3 -ErrorAction Stop
        Write-Host "  [OK]   Port $($s.Port) - $($s.Name)" -ForegroundColor Green
    } catch {
        # Even if /health isn't found, 405/404 means server IS running
        $status = $_.Exception.Response.StatusCode.value__
        if ($status -ge 400 -and $status -lt 500) {
            Write-Host "  [OK]   Port $($s.Port) - $($s.Name)" -ForegroundColor Green
        } else {
            Write-Host "  [WAIT] Port $($s.Port) - $($s.Name) (still starting...)" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Servers running in background processes  " -ForegroundColor Cyan
Write-Host "  Run .\stop_servers.ps1 to stop all  " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Save process IDs for the stop script
$processIds | ConvertTo-Json | Set-Content ".\.server_pids.json"
