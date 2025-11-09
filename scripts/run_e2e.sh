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
MCP_EXTERNAL_NETWORK="${MCP_EXTERNAL_NETWORK:-}"
MCP_EXTERNAL_NETWORK_ENABLED="${MCP_EXTERNAL_NETWORK_ENABLED:-}"

if [[ -n "$MCP_EXTERNAL_NETWORK" && -z "$MCP_EXTERNAL_NETWORK_ENABLED" ]]; then
  MCP_EXTERNAL_NETWORK_ENABLED=true
fi

export MCP_SERVICE_HOST
export MCP_EXTERNAL_NETWORK
export MCP_EXTERNAL_NETWORK_ENABLED

COMPOSE_FILE="infra/compose.test.yml"

docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
# Rebuild & recreate to ensure fresh images
docker compose -f "$COMPOSE_FILE" build rrfusion-tests
docker compose -f "$COMPOSE_FILE" up -d --force-recreate --build rrfusion-redis rrfusion-db-stub rrfusion-mcp

docker compose -f "$COMPOSE_FILE" run --rm rrfusion-tests pytest -m e2e

RESULT=$?
docker compose -f "$COMPOSE_FILE" down

exit "$RESULT"
