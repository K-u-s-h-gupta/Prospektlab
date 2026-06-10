#!/usr/bin/env bash
set -euo pipefail

dump_path="/home/azureuser/ikg_worker.fixed.dump"
container="deployment-postgres-1"
db="ikg"
user="ikg_user"

if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
  echo "Postgres container not running: $container" >&2
  exit 1
fi

echo "Copying dump into container..."
docker cp "$dump_path" "$container:/tmp/ikg_worker.dump"

echo "Restoring database..."
docker exec "$container" pg_restore -U "$user" -d "$db" --clean --if-exists /tmp/ikg_worker.dump > /home/azureuser/restore_ikg.log 2>&1
status=$?
cat /home/azureuser/restore_ikg.log
exit $status

echo "Restore complete."
