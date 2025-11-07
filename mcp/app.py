from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from rrfusion.config import get_settings
from rrfusion.mcp.service import MCPService
from rrfusion.models import (
    BlendRequest,
    GetSnippetsRequest,
    MutateRequest,
    PeekSnippetsRequest,
    ProvenanceRequest,
    SearchRequest,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = MCPService(settings)
    app.state.service = service
    try:
        yield
    finally:
        await service.close()


app = FastAPI(title="rrfusion-mcp", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp/search_fulltext")
async def search_fulltext(request: SearchRequest):
    return await app.state.service.search_lane("fulltext", request)


@app.post("/mcp/search_semantic")
async def search_semantic(request: SearchRequest):
    return await app.state.service.search_lane("semantic", request)


@app.post("/mcp/blend_frontier_codeaware")
async def blend_frontier(request: BlendRequest):
    return await app.state.service.blend(request)


@app.post("/mcp/peek_snippets")
async def peek_snippets(request: PeekSnippetsRequest):
    return await app.state.service.peek_snippets(request)


@app.post("/mcp/get_snippets")
async def get_snippets(request: GetSnippetsRequest):
    return await app.state.service.get_snippets(request)


@app.post("/mcp/mutate_run")
async def mutate_run(request: MutateRequest):
    return await app.state.service.mutate_run(request)


@app.post("/mcp/get_provenance")
async def get_provenance(request: ProvenanceRequest):
    return await app.state.service.provenance(request.run_id)
