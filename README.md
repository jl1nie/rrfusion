# rrfusion

Multi-lane patent search with **RRF fusion**, **code-aware frontier**, and **MCP** integration.

This scaffold includes:
- `AGENT.md` — the implementation brief/spec for Codex or any dev agent
- `deploy/docker-compose.yml` — spins up **Redis** locally
- `deploy/.env.example` — environment defaults

## Quick start (Redis only)

```bash
cd deploy
cp .env.example .env
docker compose up -d
docker ps  # confirm redis is up
```

## Next steps

- Point your MCP server to `REDIS_URL` from `.env`
- Hand `AGENT.md` to Codex to scaffold the FastMCP server and DB stub
- Keep large `(doc_id, score)` arrays in Redis; expose **handles** (run_id/cursor) to the LLM
