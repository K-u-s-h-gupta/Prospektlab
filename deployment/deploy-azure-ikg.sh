#!/bin/bash
# ============================================================================
# ProspektLab IKG — Azure VM Deployment Script
# Usage:  bash deployment/deploy-azure-ikg.sh
# Runs from the local Windows dev machine (Git Bash / WSL / Azure Cloud Shell).
#
# What it does:
#   1. Rsync the entire repo to the Azure VM
#   2. SSH in, rebuild Docker images, restart all IKG containers
#   3. Print live-log commands so you can watch progress immediately
# ============================================================================

set -e

AZURE_VM_IP="4.213.112.2"
AZURE_VM_USER="ar2108925"
AZURE_KEY="$HOME/.ssh/az_ssh_config/PROSPEKTLAB-IKG-RG-prospektlab-ikg-vm/id_rsa"
REMOTE_DIR="/home/${AZURE_VM_USER}/prospektlab"

# Colour helpers
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }

# ── 0. Validate SSH key ──────────────────────────────────────────────────────
if [ ! -f "$AZURE_KEY" ]; then
  warn "SSH key not found at $AZURE_KEY"
  warn "Falling back to default SSH agent / key. You may be prompted for a password."
  SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
  RSYNC_SSH="ssh ${SSH_OPTS}"
else
  SSH_OPTS="-i ${AZURE_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=15"
  RSYNC_SSH="ssh -i ${AZURE_KEY} ${SSH_OPTS}"
fi
SSH_CMD="ssh ${SSH_OPTS} ${AZURE_VM_USER}@${AZURE_VM_IP}"

# ── 1. Sync code to Azure VM ─────────────────────────────────────────────────
info "Step 1/3 — Syncing code to Azure VM ${AZURE_VM_IP}:${REMOTE_DIR} ..."

# Get the repo root (parent of deployment/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

rsync -az --progress \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'data/' \
  --exclude 'pipeline_logs/' \
  --exclude '*.egg-info/' \
  -e "${RSYNC_SSH}" \
  "${REPO_ROOT}/" \
  "${AZURE_VM_USER}@${AZURE_VM_IP}:${REMOTE_DIR}/"

success "Code synced."

# ── 2. Rebuild & restart containers on Azure VM ──────────────────────────────
info "Step 2/3 — Rebuilding Docker images and restarting containers ..."

$SSH_CMD bash -s << 'REMOTE'
set -e
REMOTE_DIR="/home/$(whoami)/prospektlab"
COMPOSE_FILE="${REMOTE_DIR}/deployment/docker-compose.ikg.yml"
ENV_FILE="${REMOTE_DIR}/backend/finagent/.env"

echo "[REMOTE] Working dir: ${REMOTE_DIR}"
cd "${REMOTE_DIR}"

# Ensure .env is present
if [ ! -f "${ENV_FILE}" ]; then
  echo "[REMOTE] ERROR: backend/finagent/.env not found at ${ENV_FILE}"
  echo "[REMOTE] Copy your .env file to the VM first:"
  echo "    scp backend/finagent/.env ${AZURE_VM_USER}@4.213.112.2:${REMOTE_DIR}/backend/finagent/.env"
  exit 1
fi

# Export MEMORY_DATABASE_URL from .env so docker-compose picks it up
export $(grep -E '^MEMORY_DATABASE_URL=' "${ENV_FILE}" | head -1)
export IKG_POSTGRES_PASSWORD="${IKG_POSTGRES_PASSWORD:-ikg_password_change_me}"

echo "[REMOTE] Pulling base images..."
docker compose -f "${COMPOSE_FILE}" pull postgres redis qdrant 2>/dev/null || true

echo "[REMOTE] Stopping old containers..."
docker compose -f "${COMPOSE_FILE}" down --remove-orphans 2>/dev/null || true

echo "[REMOTE] Building IKG worker image..."
docker compose -f "${COMPOSE_FILE}" build --no-cache celery-worker scheduler

echo "[REMOTE] Starting all services..."
docker compose -f "${COMPOSE_FILE}" up -d

echo "[REMOTE] Container status:"
docker compose -f "${COMPOSE_FILE}" ps

echo ""
echo "[REMOTE] Done. All services started."
REMOTE

success "Containers rebuilt and running."

# ── 3. Print live-log commands ───────────────────────────────────────────────
info "Step 3/3 — Ready. Use these commands on the Azure VM to run and monitor."

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  COMMANDS TO RUN ON THE AZURE VM (ssh in first, then paste)     ${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}# SSH into the Azure VM:${NC}"
echo "  ssh -i ~/.ssh/az_ssh_config/PROSPEKTLAB-IKG-RG-prospektlab-ikg-vm/id_rsa \\"
echo "      ar2108925@4.213.112.2"
echo ""
echo -e "${YELLOW}# ── Run Nifty Top 100 companies (full scrape + IKG build) ───────${NC}"
echo "  docker exec -it prospektlab-scheduler-1 \\"
echo "    python -c \""
echo "    import logging, sys"
echo "    logging.basicConfig(level=logging.INFO, stream=sys.stdout,"
echo "      format='%(asctime)s %(levelname)s %(name)s — %(message)s')"
echo "    from finagent.ikg.pipeline.orchestrator import run_nifty500_parallel_refresh"
echo "    results = run_nifty500_parallel_refresh(max_companies=100)"
echo "    for k, r in results.items():"
echo "        print(f'{k}: success={r.success} stored={r.records_stored} err={r.error}')"
echo "    \""
echo ""
echo -e "${YELLOW}# ── Or run individual phases for Nifty 100 ─────────────────────${NC}"
echo "  # Phase 1 — NSE index sync (always run first)"
echo "  docker exec prospektlab-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase nse"
echo ""
echo "  # Phase 2 — BSE shareholding patterns"
echo "  docker exec prospektlab-scheduler-1 python -c \\"
echo "    \"from finagent.ikg.pipeline.orchestrator import run_bse_shp_refresh; run_bse_shp_refresh(max_companies=100)\""
echo ""
echo "  # Phase 3 — Annual reports (XBRL-first, targeted extraction)"
echo "  docker exec prospektlab-scheduler-1 python -c \\"
echo "    \"from finagent.ikg.pipeline.orchestrator import run_annual_reports_refresh; run_annual_reports_refresh(max_companies=100)\""
echo ""
echo "  # Phase 4 — SEBI enforcement"
echo "  docker exec prospektlab-scheduler-1 python -c \\"
echo "    \"from finagent.ikg.pipeline.orchestrator import run_sebi_enforcement_refresh; run_sebi_enforcement_refresh()\""
echo ""
echo "  # Phase 5 — IKG graph build"
echo "  docker exec prospektlab-scheduler-1 python -c \\"
echo "    \"from finagent.ikg.pipeline.orchestrator import run_ikg_graph_build; run_ikg_graph_build(max_companies=100)\""
echo ""
echo -e "${YELLOW}# ── Live log monitoring ─────────────────────────────────────────${NC}"
echo "  # Follow scheduler logs (pipeline progress)"
echo "  docker logs -f prospektlab-scheduler-1"
echo ""
echo "  # Follow Celery worker logs (task execution)"
echo "  docker logs -f prospektlab-celery-worker-1"
echo ""
echo "  # Follow all IKG containers simultaneously (tmux-style)"
echo "  docker compose -f ~/prospektlab/deployment/docker-compose.ikg.yml logs -f --since=1m"
echo ""
echo "  # Filter only pipeline phase completions"
echo "  docker logs -f prospektlab-scheduler-1 2>&1 | grep -E 'NIFTY-PARALLEL|DONE|ERROR|success='"
echo ""
echo "  # Watch IKG Postgres record counts in real-time"
echo "  watch -n 10 'docker exec prospektlab-postgres-1 psql -U ikg_user -d ikg -c \\"
echo "    \"SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;\"'"
echo ""
echo -e "${CYAN}══════════════════════════════════════════════════════════════════${NC}"
echo ""
success "Deployment complete! Azure VM IP: ${AZURE_VM_IP}"
