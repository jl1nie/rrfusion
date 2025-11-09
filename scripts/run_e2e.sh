#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

if [[ -f infra/.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source infra/.env
  set +a
fi

MCP_SERVICE_HOST="${MCP_SERVICE_HOST:-rrfusion-mcp}"
MCP_EXTERNAL_NETWORK="${MCP_EXTERNAL_NETWORK:-rrfusion-test-net}"
MCP_EXTERNAL_NETWORK_ENABLED=false

export MCP_SERVICE_HOST
export MCP_EXTERNAL_NETWORK
export MCP_EXTERNAL_NETWORK_ENABLED

COMPOSE_FILE="infra/compose.stub.yml"

docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
# Rebuild & recreate to ensure fresh images
docker build -f apps/mcp-host/Dockerfile -t infra-rrfusion-tests .
docker compose -f "$COMPOSE_FILE" up -d --force-recreate --build rrfusion-redis rrfusion-db-stub rrfusion-mcp
NETWORK_NAME="${MCP_EXTERNAL_NETWORK:-rrfusion-test-net}"
until docker run --rm --network "$NETWORK_NAME" busybox nslookup "${MCP_SERVICE_HOST}" >/dev/null 2>&1; do
  sleep 1
done
docker run --rm --network "$NETWORK_NAME" --env-file infra/.env infra-rrfusion-tests pytest -m integration
docker run --rm --network "$NETWORK_NAME" --env-file infra/.env infra-rrfusion-tests pytest -m e2e

RESULT=$?
docker compose -f "$COMPOSE_FILE" down

exit "$RESULT"
