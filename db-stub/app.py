from __future__ import annotations

from fastapi import FastAPI, HTTPException, Path

from rrfusion.db_stub.generator import generate_search_results, snippets_from_request
from rrfusion.models import DBSearchResponse, GetSnippetsRequest, SearchRequest

app = FastAPI(title="rrfusion-db-stub", version="0.1.0")


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search/{lane}", response_model=DBSearchResponse)
async def search_lane(
    request: SearchRequest,
    lane: str = Path(..., pattern="^(fulltext|semantic)$"),
) -> DBSearchResponse:
    return generate_search_results(request, lane=lane)


@app.post("/snippets")
async def snippets(request: GetSnippetsRequest) -> dict[str, dict[str, str]]:
    if not request.ids:
        raise HTTPException(status_code=400, detail="ids required")
    return snippets_from_request(request)
