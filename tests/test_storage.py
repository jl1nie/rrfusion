from __future__ import annotations

import json

import fakeredis.aioredis as fakeredis
import pytest

from rrfusion.config import Settings
from rrfusion.storage import RedisStorage


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_lane_run_records_fi_and_ft_frequencies_and_doc_meta() -> None:
    redis = fakeredis.FakeRedis()
    storage = RedisStorage(redis, Settings())
    run_id = "fulltext-abc"
    lane = "fulltext"
    metadata = {
        "query": "foobar",
        "filters": [],
        "top_k": 1,
        "count_returned": 1,
        "truncated": False,
        "query_hash": "hash",
        "budget_bytes": 4096,
    }
    freq_summary = {
        "ipc": {"H04L": 1},
        "cpc": {"H04L9/32": 1},
        "fi": {"H04L1/00": 1},
        "ft": {"432": 1},
    }
    docs = [
        {
            "doc_id": "DOC-01",
            "score": 1.0,
            "title": "Title",
            "abst": "Abstract",
            "claim": "Claim",
            "desc": "Desc",
            "app_doc_id": "APP-01",
            "pub_id": "PUB-01",
            "exam_id": "EXM-01",
            "ipc_codes": ["H04L"],
            "cpc_codes": ["H04L9/32"],
            "fi_codes": ["H04L1/00"],
            "ft_codes": ["432"],
        }
    ]

    try:
        await storage.store_lane_run(
            run_id=run_id,
            lane=lane,
            query_hash=metadata["query_hash"],
            docs=docs,
            metadata=metadata,
            freq_summary=freq_summary,
        )

        freq_payload = await redis.hgetall(storage.freq_key(run_id, lane))
        assert b"fi" in freq_payload and b"ft" in freq_payload
        assert json.loads(freq_payload[b"fi"]) == freq_summary["fi"]
        assert json.loads(freq_payload[b"ft"]) == freq_summary["ft"]

        retrieved = await storage.get_freq_summary(run_id, lane)
        assert retrieved == freq_summary

        doc_meta = await storage.get_docs([docs[0]["doc_id"]])
        assert doc_meta[docs[0]["doc_id"]]["fi_codes"] == docs[0]["fi_codes"]
        assert doc_meta[docs[0]["doc_id"]]["ft_codes"] == docs[0]["ft_codes"]
    finally:
        await redis.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_freq_summary_parses_fi_ft_fields() -> None:
    redis = fakeredis.FakeRedis()
    storage = RedisStorage(redis, Settings())
    run_id = "fulltext-xyz"
    lane = "fulltext"
    payload = {
        "ipc": json.dumps({"H04L": 2}),
        "cpc": json.dumps({"H04L9/32": 2}),
        "fi": json.dumps({"H04L1/00": 1}),
        "ft": json.dumps({"432": 1}),
    }

    try:
        await redis.hset(storage.freq_key(run_id, lane), mapping=payload)
        parsed = await storage.get_freq_summary(run_id, lane)
        assert parsed["fi"] == {"H04L1/00": 1}
        assert parsed["ft"] == {"432": 1}
    finally:
        await redis.aclose()
