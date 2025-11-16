from __future__ import annotations

from fastapi import FastAPI, HTTPException, Path

from rrfusion.db_stub.generator import (
    generate_search_results,
    snippets_from_request,
    publications_from_request,
)
from rrfusion.models import (
    Cond,
    DBSearchResponse,
    FulltextParams,
    GetPublicationRequest,
    GetSnippetsRequest,
    SEARCH_FIELDS_DEFAULT,
    SemanticParams,
)

app = FastAPI(title="rrfusion-db-stub", version="0.1.0")

COLUMN_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "abstract": "abst",
    "claims": "claim",
    "description": "desc",
    "app_doc_id": "app_doc_id",
    "pub_id": "pub_id",
    "exam_id": "exam_id",
}


def _columns_to_fields(columns: list[str] | None) -> list[str]:
    if not columns:
        return SEARCH_FIELDS_DEFAULT.copy()
    fields: list[str] = []
    for column in columns:
        field = COLUMN_FIELD_MAP.get(column)
        if field and field not in fields:
            fields.append(field)
    return fields or SEARCH_FIELDS_DEFAULT.copy()


def _conditions_to_filters(conditions: list[dict[str, object]] | None) -> list[Cond]:
    if not conditions:
        return []
    inverse_column_map = {value: key for key, value in COLUMN_FIELD_MAP.items()}
    condition_filters: list[Cond] = []
    for cond in conditions:
        key = cond.get("key")
        field = inverse_column_map.get(key, key)
        lop = cond.get("lop") or "and"
        op = cond.get("op") or "in"
        value = cond.get("q")
        if value is None and "q1" in cond:
            value = [cond.get("q1"), cond.get("q2")]
        if value is None:
            continue
        try:
            condition_filters.append(
                Cond(
                    lop=lop,
                    field=field,
                    op=op,
                    value=value,
                )
            )
        except ValueError:
            continue
    return condition_filters


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search/{lane}", response_model=DBSearchResponse)
async def search_lane(
    request_body: dict[str, object],
    lane: str = Path(..., pattern="^(fulltext|semantic)$"),
) -> DBSearchResponse:
    conditions = request_body.get("conditions")
    filters = _conditions_to_filters(conditions if isinstance(conditions, list) else None)
    if "search_type" in request_body:
        query = request_body.get("q", "")
        request = FulltextParams(
            query=query,
            filters=filters,
            fields=_columns_to_fields(request_body.get("columns")),
            top_k=request_body.get("limit", 800),
            budget_bytes=request_body.get("budget_bytes", 4096),
            trace_id=request_body.get("trace_id"),
        )
    elif lane == "fulltext":
        request = FulltextParams.model_validate(request_body)
        if filters:
            request.filters = [*request.filters, *filters]
    else:
        request = SemanticParams.model_validate(request_body)
        if filters:
            request.filters = [*request.filters, *filters]
    return generate_search_results(request, lane=lane)


@app.post("/snippets")
async def snippets(request: GetSnippetsRequest) -> dict[str, dict[str, str]]:
    if not request.ids:
        raise HTTPException(status_code=400, detail="ids required")
    return snippets_from_request(request)


@app.post("/publications")
async def publications(request: GetPublicationRequest) -> dict[str, dict[str, str]]:
    if not request.ids:
        raise HTTPException(status_code=400, detail="ids required")
    return publications_from_request(request)
