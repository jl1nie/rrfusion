"""Deterministic random data generator for the DB stub."""

from __future__ import annotations

import hashlib
import os
import random
from collections import Counter

from ..models import (
    DBSearchResponse,
    FulltextParams,
    GetPublicationRequest,
    GetSnippetsRequest,
    Meta,
    SemanticParams,
    SearchItem,
)
from ..utils import random_doc_id, truncate_field

WORDS = [
    "quantum",
    "optical",
    "network",
    "fusion",
    "semiconductor",
    "antennas",
    "wireless",
    "battery",
    "circuit",
    "neural",
    "synthesis",
    "hydrogen",
    "blockchain",
    "latency",
    "compression",
    "diagnostics",
    "robotics",
    "control",
    "filter",
    "resonator",
]

IPC_CODES = ["H04L", "H04W", "G06F", "H01L", "G02F", "A61B", "C07D", "B60L"]
CPC_CODES = [
    "H04L9/32",
    "H04W72/04",
    "G06F16/27",
    "H01L29/12",
    "G02F1/13",
    "A61B5/00",
    "C07D401/12",
    "B60L11/18",
]
FI_CODES = ["H04L1/00", "H04W24/00", "G06F3/00", "B60L3/00"]
FT_CODES = ["432", "562", "H439", "G261"]

DEFAULT_MAX_RESULTS = 2000


def _resolve_max_results() -> int:
    raw = os.getenv("STUB_MAX_RESULTS")
    if not raw:
        return DEFAULT_MAX_RESULTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_RESULTS
    return max(1, min(10_000, value))


MAX_RESULTS = _resolve_max_results()


def _seed(value: str) -> random.Random:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _paragraph(rng: random.Random, sentences: int = 2, words: int = 12) -> str:
    parts = []
    for _ in range(sentences):
        chunk = " ".join(rng.choice(WORDS) for _ in range(words))
        parts.append(chunk.capitalize() + ".")
    return " ".join(parts)


def _doc_meta(doc_id: str) -> dict:
    rng = _seed(doc_id)
    ipc_codes = sorted(set(rng.sample(IPC_CODES, k=rng.randint(1, 3))))
    cpc_codes = sorted(set(rng.sample(CPC_CODES, k=rng.randint(1, 3))))
    fi_codes = sorted(set(rng.sample(FI_CODES, k=rng.randint(0, 2))))
    ft_codes = sorted(set(rng.sample(FT_CODES, k=rng.randint(0, 2))))
    title = f"{rng.choice(WORDS).title()} {rng.choice(WORDS).title()} system {doc_id[-3:]}"
    abst = _paragraph(rng, sentences=2, words=10)
    claim = _paragraph(rng, sentences=1, words=14)
    description = _paragraph(rng, sentences=4, words=12)
    app_doc_id = doc_id
    pub_id = f"DOC{doc_id[-6:]}"
    exam_id = f"EXAM{doc_id[-5:].upper()}"
    return {
        "doc_id": doc_id,
        "title": title,
        "abst": abst,
        "claim": claim,
        "desc": description,
        "app_doc_id": app_doc_id,
        "pub_id": pub_id,
        "exam_id": exam_id,
        "ipc_codes": ipc_codes,
        "cpc_codes": cpc_codes,
        "fi_codes": fi_codes,
        "ft_codes": ft_codes,
    }


def generate_search_results(
    request: FulltextParams | SemanticParams, *, lane: str
) -> DBSearchResponse:
    limit = min(request.top_k, MAX_RESULTS)
    query = request.query if isinstance(request, FulltextParams) else request.text
    rng = _seed(f"{lane}:{query}:{limit}")
    seen: set[str] = set()
    items: list[SearchItem] = []
    ipc_freq: Counter[str] = Counter()
    cpc_freq: Counter[str] = Counter()
    fi_freq: Counter[str] = Counter()
    ft_freq: Counter[str] = Counter()

    for rank in range(limit):
        doc_id = random_doc_id(rng)
        while doc_id in seen:
            doc_id = random_doc_id(rng)
        seen.add(doc_id)
        meta = _doc_meta(doc_id)
        score = 1.0 / (rank + 1 + rng.random())
        ipc_freq.update(meta["ipc_codes"])
        cpc_freq.update(meta["cpc_codes"])
        fi_freq.update(meta["fi_codes"])
        ft_freq.update(meta["ft_codes"])
        items.append(SearchItem(**meta, score=round(score, 6)))

    return DBSearchResponse(
        items=items,
        code_freqs={
            "ipc": dict(ipc_freq),
            "cpc": dict(cpc_freq),
            "fi": dict(fi_freq),
            "ft": dict(ft_freq),
        },
        meta=Meta(
            lane=lane,
            top_k=request.top_k,
            params={
                "query": getattr(request, "query", None)
                or getattr(request, "text", None),
                "filters": [cond.model_dump() for cond in request.filters],
                "fields": getattr(request, "fields", None),
            },
            trace_id=request.trace_id,
        ),
    )


def snippets_from_request(request: GetSnippetsRequest) -> dict[str, dict[str, str]]:
    response: dict[str, dict[str, str]] = {}
    for doc_id in request.ids:
        meta = _doc_meta(doc_id)
        payload: dict[str, str] = {}
        for field in request.fields:
            value = meta.get(field, "")
            limit = request.per_field_chars.get(field, len(value)) if request.per_field_chars else len(value)
            payload[field] = truncate_field(value, limit)
        response[doc_id] = payload
    return response


def publications_from_request(
    request: GetPublicationRequest,
) -> dict[str, dict[str, str]]:
    response: dict[str, dict[str, str]] = {}
    for doc_id in request.ids:
        meta = _doc_meta(doc_id)
        payload: dict[str, str] = {}
        for field in request.fields:
            payload[field] = meta.get(field, "")
        response[doc_id] = payload
    return response


__all__ = [
    "generate_search_results",
    "snippets_from_request",
    "publications_from_request",
]
