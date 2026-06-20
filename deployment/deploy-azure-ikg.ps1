# ============================================================================
# ProspektLab IKG — Azure VM Deployment Script (Windows PowerShell 5.1)
# Usage:  .\deployment\deploy-azure-ikg.ps1
# Run from: D:\PROSPEKTLAB (repo root)
# ============================================================================

$AZURE_VM_IP   = "4.213.112.2"
$AZURE_VM_USER = "ar2108925"
$SSH_KEY       = "D:\PROSPEKTLAB\deployment\az_ssh_config\PROSPEKTLAB-IKG-RG-prospektlab-ikg-vm\id_rsa"
$REMOTE_DIR    = "/home/$AZURE_VM_USER/prospektlab"
$LOCAL_ROOT    = "D:\PROSPEKTLAB"
$COMPOSE_FILE  = "$REMOTE_DIR/deployment/docker-compose.ikg.yml"
$ENV_FILE      = "$REMOTE_DIR/backend/finagent/.env"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  ProspektLab IKG --- Azure VM Deployment" -ForegroundColor Cyan
Write-Host "  VM: $AZURE_VM_IP   User: $AZURE_VM_USER" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Sync code to Azure VM ────────────────────────────────────────────
Write-Host "[1/3] Syncing code to Azure VM..." -ForegroundColor Yellow

$SSH_TARGET = "${AZURE_VM_USER}@${AZURE_VM_IP}"

# Try WSL rsync (fastest), then Git-Bash rsync, then SCP tar fallback
$wslAvail   = $null -ne (Get-Command wsl   -ErrorAction SilentlyContinue)
$rsyncAvail = $null -ne (Get-Command rsync -ErrorAction SilentlyContinue)

if ($wslAvail) {
    Write-Host "  Using WSL rsync..." -ForegroundColor Gray
    # Convert Windows paths to WSL paths
    $wslKey = $SSH_KEY   -replace '^([A-Za-z]):\\', { '/mnt/' + $_.Groups[1].Value.ToLower() + '/' } -replace '\\', '/'
    $wslSrc = $LOCAL_ROOT -replace '^([A-Za-z]):\\', { '/mnt/' + $_.Groups[1].Value.ToLower() + '/' } -replace '\\', '/'

    wsl rsync -az --progress `
        "--exclude=.git/" "--exclude=__pycache__/" "--exclude=*.pyc" `
        "--exclude=.venv/" "--exclude=node_modules/" `
        "--exclude=frontend/dist/" "--exclude=frontend/node_modules/" `
        "--exclude=data/" "--exclude=pipeline_logs/" "--exclude=*.egg-info/" `
        -e "ssh -i $wslKey -o StrictHostKeyChecking=no -o ConnectTimeout=15" `
        "${wslSrc}/" "${SSH_TARGET}:${REMOTE_DIR}/"

} elseif ($rsyncAvail) {
    Write-Host "  Using rsync..." -ForegroundColor Gray
    rsync -az --progress `
        "--exclude=.git/" "--exclude=__pycache__/" "--exclude=*.pyc" `
        "--exclude=.venv/" "--exclude=node_modules/" `
        "--exclude=frontend/dist/" "--exclude=frontend/node_modules/" `
        "--exclude=data/" "--exclude=pipeline_logs/" "--exclude=*.egg-info/" `
        -e "ssh -i `"$SSH_KEY`" -o StrictHostKeyChecking=no -o ConnectTimeout=15" `
        "${LOCAL_ROOT}/" "${SSH_TARGET}:${REMOTE_DIR}/"

} else {
    Write-Host "  rsync not found — using tar + SCP fallback (slower)..." -ForegroundColor Yellow
    Write-Host "  TIP: Install WSL for faster deploys next time." -ForegroundColor Gray

    $TMP_TAR = "$env:TEMP\prospektlab_deploy.tar.gz"
    Push-Location $LOCAL_ROOT
    tar -czf $TMP_TAR `
        --exclude=".git" --exclude="__pycache__" --exclude=".venv" `
        --exclude="data" --exclude="pipeline_logs" `
        "--exclude=frontend/node_modules" "--exclude=frontend/dist" `
        finagent deployment pyproject.toml scripts
    Pop-Location

    scp -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15 `
        $TMP_TAR "${SSH_TARGET}:/tmp/prospektlab_deploy.tar.gz"

    # SSH: extract tarball — semicolons used so PowerShell does not see bash operators
    $extractCmd = "mkdir -p $REMOTE_DIR ; tar -xzf /tmp/prospektlab_deploy.tar.gz -C $REMOTE_DIR ; rm /tmp/prospektlab_deploy.tar.gz"
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15 $SSH_TARGET $extractCmd

    Remove-Item $TMP_TAR -Force
}

Write-Host "[1/3] Code synced." -ForegroundColor Green

# ── Step 2: Rebuild Docker on Azure VM ───────────────────────────────────────
Write-Host ""
Write-Host "[2/3] Rebuilding Docker images on Azure VM..." -ForegroundColor Yellow

# Use a single-quoted here-string for the bash script so PowerShell does NOT
# expand $variables inside it — the remote shell handles all substitution.
# We pass the few paths we need as environment variables via -o SendEnv or
# prepend them as inline shell assignments.
$remoteEnv = "REMOTE_DIR=$REMOTE_DIR COMPOSE_FILE=$COMPOSE_FILE ENV_FILE=$ENV_FILE"

$remoteBuild = @'
set -e

echo "[REMOTE] cd $REMOTE_DIR"
cd "$REMOTE_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo ""
  echo "ERROR: backend/finagent/.env not found at $ENV_FILE"
  echo "Upload it once with:"
  echo "  scp backend/finagent/.env ar2108925@4.213.112.2:$ENV_FILE"
  echo ""
  exit 1
fi

# Source .env so MEMORY_DATABASE_URL is available to docker-compose interpolation
set -a
source "$ENV_FILE"
set +a

echo "[REMOTE] Pulling infrastructure images (postgres, redis, qdrant)..."
docker compose -f "$COMPOSE_FILE" pull postgres redis qdrant 2>/dev/null || true

echo "[REMOTE] Stopping old containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

echo "[REMOTE] Building worker/scheduler image (no-cache)..."
docker compose -f "$COMPOSE_FILE" build --no-cache celery-worker scheduler

echo "[REMOTE] Starting all services..."
docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "[REMOTE] Container status:"
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "[REMOTE] Done."
'@

# Prepend the variable assignments so the single-quoted script can use them
$fullScript = "$remoteEnv`n$remoteBuild"

ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30 $SSH_TARGET $fullScript

Write-Host "[2/3] Containers rebuilt and running." -ForegroundColor Green

# ── Step 3: Print ready-to-paste commands ────────────────────────────────────
Write-Host ""
Write-Host "[3/3] Deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  PASTE THESE COMMANDS INTO THE AZURE VM SSH TERMINAL" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "# SSH into the VM:" -ForegroundColor Yellow
Write-Host "  ssh -i `"D:\PROSPEKTLAB\deployment\az_ssh_config\PROSPEKTLAB-IKG-RG-prospektlab-ikg-vm\id_rsa`" ar2108925@4.213.112.2"

Write-Host ""
Write-Host "# ---- RUN NIFTY TOP 100 (full pipeline) -----------------------" -ForegroundColor Yellow
Write-Host "  docker exec -it prospektlab-scheduler-1 python -c `"`"" -NoNewline
Write-Host ""
Write-Host @'
docker exec -it prospektlab-scheduler-1 python -c "
import logging, sys
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
  format='%(asctime)s %(levelname)-8s %(name)s -- %(message)s')
from finagent.ikg.pipeline.orchestrator import run_nifty500_parallel_refresh
results = run_nifty500_parallel_refresh(max_companies=100)
print()
print('=== PIPELINE SUMMARY ===')
for k, r in sorted(results.items()):
    status = 'OK  ' if r.success else 'FAIL'
    print(f'  [{status}] {k}: stored={r.records_stored} failed={r.records_failed} dur={r.duration_s:.0f}s err={r.error or \"-\"}')
"
'@

Write-Host ""
Write-Host "# ---- LIVE LOG MONITORING -------------------------------------" -ForegroundColor Yellow
Write-Host ""
Write-Host "  # All scheduler pipeline logs (main view):"
Write-Host "  docker logs -f prospektlab-scheduler-1"
Write-Host ""
Write-Host "  # Filter to phase completions only:"
Write-Host "  docker logs -f prospektlab-scheduler-1 2>&1 | grep -E 'NIFTY-PARALLEL|DONE|success=|ERROR'"
Write-Host ""
Write-Host "  # Celery worker task execution:"
Write-Host "  docker logs -f prospektlab-celery-worker-1"
Write-Host ""
Write-Host "  # All containers at once:"
Write-Host "  docker compose -f ~/prospektlab/deployment/docker-compose.ikg.yml logs -f"
Write-Host ""
Write-Host "  # Watch IKG record counts live (every 10s):"
Write-Host "  watch -n 10 'docker exec prospektlab-postgres-1 psql -U ikg_user -d ikg -c \\"
Write-Host '    "SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;"'"'"
Write-Host ""
Write-Host "  # Check graph vertices + edges:"
Write-Host "  docker exec prospektlab-postgres-1 psql -U ikg_user -d ikg -c \"SELECT (SELECT COUNT(*) FROM ikg_vertices) AS vertices, (SELECT COUNT(*) FROM ikg_edges) AS edges;\""
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
