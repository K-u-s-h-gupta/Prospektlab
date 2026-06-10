#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${IKG_COMPOSE_FILE:-${SCRIPT_DIR}/docker-compose.ikg.yml}"
WORKER_REPLICAS="${IKG_WORKER_REPLICAS:-2}"
LOG_DIR="${IKG_PIPELINE_LOG_DIR:-${PROJECT_DIR}/pipeline_logs}"
LOG_FILE="${LOG_DIR}/ikg_watchdog_$(date +%Y%m%d).log"

mkdir -p "${LOG_DIR}"

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "${LOG_FILE}"
}

compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

health_status() {
  local health_json status
  health_json="$(compose exec -T scheduler python -m finagent.ikg.pipeline.orchestrator --phase health 2>/dev/null || true)"
  if [[ -z "${health_json}" ]]; then
    printf 'unknown'
    return
  fi
  status="$(printf '%s' "${health_json}" | grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 | cut -d'"' -f4 || true)"
  printf '%s' "${status:-unknown}"
}

ensure_stack() {
  log "Ensuring IKG compose stack is running"
  compose up -d --scale celery-worker="${WORKER_REPLICAS}"
}

main() {
  if ! command -v docker >/dev/null 2>&1; then
    log "docker CLI is not available"
    exit 1
  fi

  ensure_stack

  local status
  status="$(health_status)"
  log "Health status: ${status}"

  if [[ "${status}" == "error" || "${status}" == "unknown" ]]; then
    log "Restarting scheduler and workers after unhealthy probe"
    compose restart scheduler celery-worker || true
    sleep 10
    status="$(health_status)"
    log "Health status after restart: ${status}"
  fi

  if [[ "${status}" == "error" ]]; then
    log "Watchdog finished with unhealthy status"
    exit 2
  fi
}

main "$@"
