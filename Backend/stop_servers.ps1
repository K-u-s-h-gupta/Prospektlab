# ORACLE FIOS - Stop All MCP Servers
# Usage: .\stop_servers.ps1

Write-Host ""
Write-Host "Stopping all ORACLE MCP servers..." -ForegroundColor Yellow

# Stop by port
@(8001, 8002, 8003, 8004, 8005) | ForEach-Object {
    $port = $_
    $pids = netstat -ano | Select-String ":$port " | ForEach-Object {
        ($_ -split '\s+')[-1]
    } | Sort-Object -Unique | Where-Object { $_ -match '^\d+$' }
    foreach ($p in $pids) {
        try {
            taskkill /PID $p /F 2>$null | Out-Null
            Write-Host "  [STOPPED] Port $port (PID $p)" -ForegroundColor Green
        } catch {}
    }
}

# Stop tracked background processes too
if (Test-Path ".\.server_pids.json") {
    try {
        $tracked = Get-Content ".\.server_pids.json" | ConvertFrom-Json
        foreach ($entry in @($tracked)) {
            if ($entry.PID) {
                try {
                    Stop-Process -Id $entry.PID -Force -ErrorAction SilentlyContinue
                    Write-Host "  [STOPPED] Tracked PID $($entry.PID) ($($entry.Name))" -ForegroundColor Green
                } catch {}
            }
        }
    } catch {}
    Remove-Item ".\.server_pids.json" -ErrorAction SilentlyContinue
}

Remove-Item ".\.server_pids.txt" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "All servers stopped." -ForegroundColor Green
Write-Host ""
