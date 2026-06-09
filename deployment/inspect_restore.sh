#!/usr/bin/env bash
set -u

container="deployment-postgres-1"
dump="/tmp/ikg_worker.dump"

echo "== container =="
docker ps --format '{{.Names}}' | grep -x "$container" || true

echo "== dump file =="
docker exec "$container" ls -lh "$dump" || true

echo "== pg_restore list =="
set +e
docker exec "$container" pg_restore -l "$dump"
echo "exit_code=$?"
