"""Redis persistence helpers for runs, docs, and snippets."""

from __future__ import annotations

import json
import time
from typing import Any, Iterable, Sequence

from redis.asyncio import Redis

from .config import Settings


class RedisStorage:
    """Typed helpers over Redis for runs + doc caches."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    # ---- Key helpers -----------------------------------------------------
    def lane_key(self, query_hash: str, lane: str) -> str:
        return f"z:{self.settings.snapshot}:{query_hash}:{lane}"

    @staticmethod
    def rrf_key(run_id: str) -> str:
        return f"z:rrf:{run_id}"

    @staticmethod
    def doc_key(doc_id: str) -> str:
        return f"h:doc:{doc_id}"

    @staticmethod
    def run_key(run_id: str) -> str:
        return f"h:run:{run_id}"

    @staticmethod
    def freq_key(run_id: str, lane: str) -> str:
        return f"h:freq:{run_id}:{lane}"

    # ---- Persistence -----------------------------------------------------
    async def store_lane_run(
        self,
        *,
        run_id: str,
        lane: str,
        query_hash: str,
        docs: Sequence[dict[str, Any]],
        metadata: dict[str, Any],
        freq_summary: dict[str, dict[str, int]],
    ) -> None:
        """Persist lane docs, per-doc metadata, freq summary, and run metadata."""

        lane_key = self.lane_key(query_hash, lane)
        data_ttl = self.settings.data_ttl_hours * 3600
        snippet_ttl = self.settings.snippet_ttl_hours * 3600
        now = int(time.time())

        pipe = self.redis.pipeline(transaction=False)
        pipe.delete(lane_key)

        z_mapping = {doc["doc_id"]: float(doc["score"]) for doc in docs}
        if z_mapping:
            pipe.zadd(lane_key, z_mapping)

        pipe.expire(lane_key, data_ttl)

        for doc in docs:
            doc_key = self.doc_key(doc["doc_id"])
            doc_payload = {
                "title": doc.get("title", ""),
                "abst": doc.get("abst", ""),
                "claim": doc.get("claim", ""),
                "description": doc.get("description", ""),
                "ipc_codes": json.dumps(doc.get("ipc_codes", [])),
                "cpc_codes": json.dumps(doc.get("cpc_codes", [])),
                "fi_codes": json.dumps(doc.get("fi_codes", [])),
                "ft_codes": json.dumps(doc.get("ft_codes", [])),
            }
            pipe.hset(doc_key, mapping=doc_payload)
            pipe.expire(doc_key, snippet_ttl)

        freq_key = self.freq_key(run_id, lane)
        pipe.hset(
            freq_key,
            mapping={
                "ipc": json.dumps(freq_summary.get("ipc", {})),
                "cpc": json.dumps(freq_summary.get("cpc", {})),
            },
        )
        pipe.expire(freq_key, data_ttl)

        run_key = self.run_key(run_id)
        run_meta = {
            **metadata,
            "run_id": run_id,
            "lane": lane,
            "lane_key": lane_key,
            "freq_key": freq_key,
            "run_type": "lane",
            "created_at": now,
        }
        pipe.hset(run_key, mapping={"meta": json.dumps(run_meta)})
        pipe.expire(run_key, data_ttl)

        await pipe.execute()

    async def upsert_docs(self, docs: Sequence[dict[str, Any]]) -> None:
        if not docs:
            return
        snippet_ttl = self.settings.snippet_ttl_hours * 3600
        pipe = self.redis.pipeline(transaction=False)
        for doc in docs:
            doc_key = self.doc_key(doc["doc_id"])
            doc_payload = {
                "title": doc.get("title", ""),
                "abst": doc.get("abst", ""),
                "claim": doc.get("claim", ""),
                "description": doc.get("description", ""),
                "ipc_codes": json.dumps(doc.get("ipc_codes", [])),
                "cpc_codes": json.dumps(doc.get("cpc_codes", [])),
                "fi_codes": json.dumps(doc.get("fi_codes", [])),
                "ft_codes": json.dumps(doc.get("ft_codes", [])),
            }
            pipe.hset(doc_key, mapping=doc_payload)
            pipe.expire(doc_key, snippet_ttl)
        await pipe.execute()

    async def store_rrf_run(
        self,
        *,
        run_id: str,
        scores: Sequence[tuple[str, float]],
        metadata: dict[str, Any],
    ) -> None:
        key = self.rrf_key(run_id)
        data_ttl = self.settings.data_ttl_hours * 3600
        pipe = self.redis.pipeline(transaction=False)
        pipe.delete(key)
        if scores:
            pipe.zadd(key, {doc_id: float(score) for doc_id, score in scores})
        pipe.expire(key, data_ttl)

        run_key = self.run_key(run_id)
        run_meta = {
            **metadata,
            "run_id": run_id,
            "rrf_key": key,
            "run_type": metadata.get("run_type", "fusion"),
            "created_at": int(time.time()),
        }
        pipe.hset(run_key, mapping={"meta": json.dumps(run_meta)})
        pipe.expire(run_key, data_ttl)
        await pipe.execute()

    async def get_run_meta(self, run_id: str) -> dict[str, Any] | None:
        data = await self.redis.hget(self.run_key(run_id), "meta")
        if not data:
            return None
        return json.loads(data)

    async def get_docs(self, doc_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        docs: dict[str, dict[str, Any]] = {}
        for doc_id in doc_ids:
            payload = await self.redis.hgetall(self.doc_key(doc_id))
            if not payload:
                continue
            if payload and isinstance(next(iter(payload.keys())), bytes):
                decoded: dict[str, Any] = {}
                for key, value in payload.items():
                    str_key = key.decode("utf-8") if isinstance(key, bytes) else key
                    str_value = value.decode("utf-8") if isinstance(value, bytes) else value
                    decoded[str_key] = str_value
                payload = decoded
            docs[doc_id] = {
                "title": payload.get("title", ""),
                "abst": payload.get("abst", ""),
                "claim": payload.get("claim", ""),
                "description": payload.get("description", ""),
                "ipc_codes": json.loads(payload.get("ipc_codes", "[]")),
                "cpc_codes": json.loads(payload.get("cpc_codes", "[]")),
                "fi_codes": json.loads(payload.get("fi_codes", "[]")),
                "ft_codes": json.loads(payload.get("ft_codes", "[]")),
            }
        return docs

    async def zslice(
        self,
        key: str,
        start: int,
        stop: int,
        *,
        desc: bool = True,
    ) -> list[tuple[str, float]]:
        if desc:
            rows = await self.redis.zrevrange(key, start, stop, withscores=True)
        else:
            rows = await self.redis.zrange(key, start, stop, withscores=True)
        return [(member.decode("utf-8"), float(score)) for member, score in rows]

    async def zrange_all(self, key: str, *, desc: bool = True) -> list[tuple[str, float]]:
        return await self.zslice(key, 0, -1, desc=desc)

    async def set_run_meta(self, run_id: str, meta: dict[str, Any]) -> None:
        key = self.run_key(run_id)
        data_ttl = self.settings.data_ttl_hours * 3600
        await self.redis.hset(key, mapping={"meta": json.dumps(meta)})
        await self.redis.expire(key, data_ttl)


__all__ = ["RedisStorage"]
