#!/usr/bin/env bash
set -eu

REGISTRY="prospektlaboutreach2026.azurecr.io"
IMAGE="${REGISTRY}/ikg-worker:20260626"
ROOT="/home/ar2108925/prospektlab"
COMPOSE_FILE="${ROOT}/deployment/docker-compose.ikg.yml"
ACR_USER="prospektlaboutreach2026"
ACR_PASS="__ACR_PASS__"

echo "==> Logging into ACR"
echo "${ACR_PASS}" | docker login "${REGISTRY}" -u "${ACR_USER}" --password-stdin

echo "==> Pulling ${IMAGE}"
docker pull "${IMAGE}"

echo "==> Tagging for compose services"
docker tag "${IMAGE}" deployment-celery-worker:latest
docker tag "${IMAGE}" deployment-scheduler:latest

cd "${ROOT}"
echo "==> Recreating celery-worker and scheduler"
docker compose -f "${COMPOSE_FILE}" up -d --force-recreate --no-build celery-worker scheduler

echo "==> Container status"
docker compose -f "${COMPOSE_FILE}" ps

echo "==> IKG scraper deploy complete"
