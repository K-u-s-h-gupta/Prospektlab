param(
    [string]$ResourceGroup = "PROSPEKTLAB-SCRAPER-RG",
    [string]$VmName = "prospektlab-scraper-vm",
    [int]$DefaultReplicas = 3,
    [int]$BulkReplicas = 2,
    [int]$PriorityReplicas = 1,
    [int]$PlaywrightReplicas = 1,
    [int]$MinFreeGb = 50,
    [switch]$RestartWorkers
)

$ErrorActionPreference = "Stop"

function Invoke-ScraperVmCommand {
    param([Parameter(Mandatory = $true)][string]$Script)

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $bootstrap = "echo '$encoded' | base64 -d >/tmp/codex-scale-scraper.sh && bash /tmp/codex-scale-scraper.sh"

    az vm run-command invoke `
        --resource-group $ResourceGroup `
        --name $VmName `
        --command-id RunShellScript `
        --scripts $bootstrap `
        -o json
}

$restartFlag = if ($RestartWorkers.IsPresent) { "1" } else { "0" }

$remoteScriptTemplate = @'
set -eu

DEFAULT_REPLICAS="__DEFAULT_REPLICAS__"
BULK_REPLICAS="__BULK_REPLICAS__"
PRIORITY_REPLICAS="__PRIORITY_REPLICAS__"
PLAYWRIGHT_REPLICAS="__PLAYWRIGHT_REPLICAS__"
MIN_FREE_GB="__MIN_FREE_GB__"
RESTART_WORKERS="__RESTART_WORKERS__"

echo "CHECK_TIME $(date -u +%Y-%m-%dT%H:%M:%SZ)"

free_gb="$(df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}')"
used_pct="$(df -h / | awk 'NR==2 {print $5}')"
echo "DISK_FREE_GB=$free_gb"
echo "DISK_USED=$used_pct"
if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
  echo "ABORT disk_free_gb=$free_gb below min_free_gb=$MIN_FREE_GB"
  exit 2
fi

default_container="$(docker ps --filter 'name=worker-default' --format '{{.Names}}' | head -n 1)"
if [ -z "$default_container" ]; then
  echo "ABORT worker-default container not found"
  docker ps --format '{{.Names}} {{.Status}}'
  exit 3
fi

project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$default_container")"
workdir="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$default_container")"
config_files="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$default_container")"

if [ -z "$project" ] || [ -z "$workdir" ]; then
  echo "ABORT could not resolve compose project/workdir from $default_container"
  exit 4
fi

compose_root="$workdir"
if [ -n "$config_files" ] && [ ! -f "$compose_root/$config_files" ]; then
  parent_dir="$(dirname "$workdir")"
  if [ -f "$parent_dir/$config_files" ]; then
    compose_root="$parent_dir"
  fi
fi

if docker compose version >/dev/null 2>&1; then
  compose="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  compose="docker-compose"
else
  echo "ABORT docker compose not available"
  exit 5
fi

cd "$compose_root"

set -- -p "$project"
old_ifs="$IFS"
IFS=':'
for file in $config_files; do
  if [ -z "$file" ]; then
    continue
  fi
  if [ -f "$file" ]; then
    set -- "$@" -f "$file"
  elif [ -f "$compose_root/$file" ]; then
    set -- "$@" -f "$compose_root/$file"
  elif [ -f "$workdir/$(basename "$file")" ]; then
    set -- "$@" -f "$workdir/$(basename "$file")"
  else
    echo "ABORT compose file not found: $file"
    exit 6
  fi
done
IFS="$old_ifs"

echo "COMPOSE_PROJECT=$project"
echo "COMPOSE_WORKDIR=$workdir"
echo "COMPOSE_ROOT=$compose_root"
echo "COMPOSE_FILES=$config_files"

echo "QUEUES_BEFORE"
redis_container="$(docker ps --filter 'name=redis' --format '{{.Names}}' | head -n 1)"
if [ -n "$redis_container" ]; then
  for queue in celery default priority bulk playwright; do
    echo "$queue $(docker exec "$redis_container" redis-cli llen "$queue" 2>/dev/null || echo unknown)"
  done
else
  echo "redis missing"
fi

echo "SCALING"
$compose "$@" up -d --no-build \
  --scale worker-default="$DEFAULT_REPLICAS" \
  --scale worker-bulk="$BULK_REPLICAS" \
  --scale worker-priority="$PRIORITY_REPLICAS" \
  --scale worker-playwright="$PLAYWRIGHT_REPLICAS" \
  worker-default worker-bulk worker-priority worker-playwright

if [ "$RESTART_WORKERS" = "1" ]; then
  echo "RESTARTING_WORKERS"
  docker ps \
    --filter "label=com.docker.compose.project=$project" \
    --format '{{.Names}}' \
    | grep -E 'worker-(default|bulk|priority|playwright)' \
    | xargs -r docker restart
fi

echo "CONTAINERS_AFTER"
docker ps --format '{{.Names}}	{{.Status}}	{{.Image}}' | sort

echo "QUEUES_AFTER"
if [ -n "$redis_container" ]; then
  for queue in celery default priority bulk playwright; do
    echo "$queue $(docker exec "$redis_container" redis-cli llen "$queue" 2>/dev/null || echo unknown)"
  done
fi

echo "STATS_AFTER"
docker stats --no-stream --format '{{.Name}}	{{.CPUPerc}}	{{.MemUsage}}' | sort
'@

$remoteScript = ($remoteScriptTemplate).
    Replace("__DEFAULT_REPLICAS__", [string]$DefaultReplicas).
    Replace("__BULK_REPLICAS__", [string]$BulkReplicas).
    Replace("__PRIORITY_REPLICAS__", [string]$PriorityReplicas).
    Replace("__PLAYWRIGHT_REPLICAS__", [string]$PlaywrightReplicas).
    Replace("__MIN_FREE_GB__", [string]$MinFreeGb).
    Replace("__RESTART_WORKERS__", $restartFlag)

Invoke-ScraperVmCommand -Script $remoteScript
