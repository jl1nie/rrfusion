"""Shared helpers for hashing queries, truncating text, and byte accounting."""

from __future__ import annotations

import hashlib
import json
import random
import string
from typing import Iterable


def hash_query(query: str, filters: dict | None = None) -> str:
    payload = {"q": query, "filters": filters or {}}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def random_doc_id(rng: random.Random | None = None) -> str:
    rng = rng or random
    return "".join(rng.choice(string.digits) for _ in range(12))


def truncate_field(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    ellipsis = "..." if max_chars > 3 else ""
    slice_len = max_chars - len(ellipsis)
    return value[:slice_len] + ellipsis


def item_budget_bytes(items: Iterable[dict]) -> int:
    total = 0
    for item in items:
        total += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
    return total


__all__ = ["hash_query", "random_doc_id", "truncate_field", "item_budget_bytes"]
