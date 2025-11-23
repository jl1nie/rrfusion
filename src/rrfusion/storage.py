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
        self._code_to_id_cache: dict[str, int] = {}
        self._id_to_code_cache: dict[int, str] = {}

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

    def _code_vocab_key(self) -> str:
        return f"h:code_vocab:{self.settings.snapshot}"

    def _code_vocab_rev_key(self) -> str:
        return f"h:code_vocab_rev:{self.settings.snapshot}"

    def _code_vocab_next_key(self) -> str:
        return f"n:code_vocab_next:{self.settings.snapshot}"

    async def _map_codes_to_ids(self, codes: Iterable[str]) -> dict[str, int]:
        unique_codes = {str(code) for code in codes if code}
        if not unique_codes:
            return {}
        mapping: dict[str, int] = {}
        to_lookup: list[str] = []
        for code in unique_codes:
            cached = self._code_to_id_cache.get(code)
            if cached is not None:
                mapping[code] = cached
            else:
                to_lookup.append(code)
        if to_lookup:
            pipe = self.redis.pipeline(transaction=False)
            for code in to_lookup:
                pipe.hget(self._code_vocab_key(), code)
            lookup_results = await pipe.execute()
            new_codes: list[str] = []
            for code, raw in zip(to_lookup, lookup_results):
                if raw:
                    value = int(raw)
                    mapping[code] = value
                    self._code_to_id_cache[code] = value
                    self._id_to_code_cache[value] = code
                else:
                    new_codes.append(code)
            if new_codes:
                count = len(new_codes)
                next_id = await self.redis.incrby(self._code_vocab_next_key(), count)
                start_id = next_id - count + 1
                pipe = self.redis.pipeline(transaction=False)
                for offset, code in enumerate(new_codes):
                    code_id = start_id + offset
                    mapping[code] = code_id
                    self._code_to_id_cache[code] = code_id
                    self._id_to_code_cache[code_id] = code
                    pipe.hset(self._code_vocab_key(), code, code_id)
                    pipe.hset(self._code_vocab_rev_key(), str(code_id), code)
                await pipe.execute()
        return mapping

    async def _decode_code_ids(self, ids: Sequence[int]) -> list[str]:
        if not ids:
            return []
        result: list[str | None] = []
        missing: list[tuple[int, int]] = []
        for idx, code_id in enumerate(ids):
            if code_id is None:
                result.append(None)
                continue
            cached = self._id_to_code_cache.get(code_id)
            if cached is not None:
                result.append(cached)
            else:
                result.append(None)
                missing.append((idx, code_id))
        if missing:
            pipe = self.redis.pipeline(transaction=False)
            for _idx, code_id in missing:
                pipe.hget(self._code_vocab_rev_key(), str(code_id))
            lookup_results = await pipe.execute()
            for (idx, code_id), raw in zip(missing, lookup_results):
                if raw:
                    code = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                else:
                    code = str(code_id)
                result[idx] = code
                self._id_to_code_cache[code_id] = code
                self._code_to_id_cache[code] = code_id
        decoded: list[str] = []
        for idx, value in enumerate(result):
            if value is not None:
                decoded.append(value)
            else:
                code_id = ids[idx]
                decoded.append(str(code_id) if code_id is not None else "")
        return decoded

    async def _encode_codes_for_docs(self, docs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        code_fields = ("ipc_codes", "cpc_codes", "fi_codes", "ft_codes")
        all_codes: set[str] = set()
        for doc in docs:
            for taxonomy in code_fields:
                for code in doc.get(taxonomy, []) or []:
                    if code:
                        all_codes.add(str(code))
        if not all_codes:
            encoded_docs: list[dict[str, Any]] = []
            for doc in docs:
                encoded = dict(doc)
                for taxonomy in code_fields:
                    encoded[taxonomy] = []
                encoded_docs.append(encoded)
            return encoded_docs
        mapping = await self._map_codes_to_ids(all_codes)
        encoded_docs: list[dict[str, Any]] = []
        for doc in docs:
            encoded = dict(doc)
            for taxonomy in code_fields:
                values = doc.get(taxonomy, []) or []
                encoded_values = [mapping[str(code)] for code in values if str(code) in mapping]
                encoded[taxonomy] = encoded_values
            encoded_docs.append(encoded)
        return encoded_docs

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

        encoded_docs = await self._encode_codes_for_docs(docs)

        # Stage 1: put scores into a sorted set keyed by query hash + lane
        lane_key = self.lane_key(query_hash, lane)
        data_ttl = self.settings.data_ttl_hours * 3600
        snippet_ttl = self.settings.snippet_ttl_hours * 3600
        now = int(time.time())

        pipe = self.redis.pipeline(transaction=False)
        pipe.delete(lane_key)

        z_mapping = {doc["doc_id"]: float(doc["score"]) for doc in encoded_docs}
        if z_mapping:
            pipe.zadd(lane_key, z_mapping)

        pipe.expire(lane_key, data_ttl)

        # Stage 2: cache document metadata for snippet retrieval
        for doc in encoded_docs:
            doc_key = self.doc_key(doc["doc_id"])
            doc_payload = {
                "title": doc.get("title", ""),
                "abst": doc.get("abst", ""),
                "claim": doc.get("claim", ""),
                "desc": doc.get("desc", ""),
                "app_doc_id": doc.get("app_doc_id", ""),
                "pub_id": doc.get("pub_id", ""),
                "exam_id": doc.get("exam_id", ""),
                "app_date": doc.get("app_date", ""),
                "pub_date": doc.get("pub_date", ""),
                "apm_applicants": doc.get("apm_applicants", ""),
                "cross_en_applicants": doc.get("cross_en_applicants", ""),
                "ipc_codes": json.dumps(doc.get("ipc_codes", [])),
                "cpc_codes": json.dumps(doc.get("cpc_codes", [])),
                "fi_codes": json.dumps(doc.get("fi_codes", [])),
                "ft_codes": json.dumps(doc.get("ft_codes", [])),
            }
            pipe.hset(doc_key, mapping=doc_payload)
            pipe.expire(doc_key, snippet_ttl)

        # Stage 3: persist taxonomy frequencies for mining
        freq_key = self.freq_key(run_id, lane)
        pipe.hset(
            freq_key,
            mapping={
                "ipc": json.dumps(freq_summary.get("ipc", {})),
                "cpc": json.dumps(freq_summary.get("cpc", {})),
                "fi": json.dumps(freq_summary.get("fi", {})),
                "ft": json.dumps(freq_summary.get("ft", {})),
            },
        )
        pipe.expire(freq_key, data_ttl)

        # Stage 4: index run metadata so we can later mutate / peek
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
        encoded_docs = await self._encode_codes_for_docs(docs)
        snippet_ttl = self.settings.snippet_ttl_hours * 3600
        pipe = self.redis.pipeline(transaction=False)
        for doc in encoded_docs:
            doc_key = self.doc_key(doc["doc_id"])
            doc_payload = {
                "title": doc.get("title", ""),
                "abst": doc.get("abst", ""),
                "claim": doc.get("claim", ""),
                "desc": doc.get("desc", ""),
                "app_doc_id": doc.get("app_doc_id", ""),
                "pub_id": doc.get("pub_id", ""),
                "exam_id": doc.get("exam_id", ""),
                "app_date": doc.get("app_date", ""),
                "pub_date": doc.get("pub_date", ""),
                "apm_applicants": doc.get("apm_applicants", ""),
                "cross_en_applicants": doc.get("cross_en_applicants", ""),
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
            def _load_code_list(key: str) -> list[Any]:
                raw_value = payload.get(key, "[]")
                if isinstance(raw_value, bytes):
                    raw_value = raw_value.decode("utf-8")
                return json.loads(raw_value)

            async def _decode_codes(key: str) -> list[str]:
                raw = _load_code_list(key)
                if raw and all(isinstance(item, int) for item in raw):
                    return await self._decode_code_ids(raw)
                return [str(item) for item in raw if item]

            docs[doc_id] = {
                "title": payload.get("title", ""),
                "abst": payload.get("abst", ""),
                "claim": payload.get("claim", ""),
                "desc": payload.get("desc", ""),
                "app_doc_id": payload.get("app_doc_id", ""),
                "pub_id": payload.get("pub_id", ""),
                "exam_id": payload.get("exam_id", ""),
                "apm_applicants": payload.get("apm_applicants", ""),
                "cross_en_applicants": payload.get("cross_en_applicants", ""),
                "ipc_codes": await _decode_codes("ipc_codes"),
                "cpc_codes": await _decode_codes("cpc_codes"),
                "fi_codes": await _decode_codes("fi_codes"),
                "ft_codes": await _decode_codes("ft_codes"),
            }
        return docs

    async def get_freq_summary(
        self, run_id: str, lane: str
    ) -> dict[str, dict[str, int]] | None:
        data = await self.redis.hgetall(self.freq_key(run_id, lane))
        if not data:
            return None
        if data and isinstance(next(iter(data.keys())), bytes):
            decoded_data = {
                key.decode("utf-8"): value for key, value in data.items()
            }
            data = decoded_data
        summary: dict[str, dict[str, int]] = {}
        for taxonomy in ("ipc", "cpc", "fi", "ft"):
            raw = data.get(taxonomy)
            if not raw:
                summary[taxonomy] = {}
                continue
            value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            summary[taxonomy] = json.loads(value)
        return summary

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
