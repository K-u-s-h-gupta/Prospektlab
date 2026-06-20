#!/usr/bin/env bash
set -euo pipefail

docker exec deployment-scheduler-1 python -m pip install --no-cache-dir 'docling>=2.0.0'
docker exec deployment-celery-worker-1 python -m pip install --no-cache-dir 'docling>=2.0.0'
docker exec deployment-scheduler-1 python -c 'import docling; print("scheduler_docling_ok", docling.__version__)'
docker exec deployment-celery-worker-1 python -c 'import docling; print("worker_docling_ok", docling.__version__)'

