"""Helpers for peek/get snippet shaping."""

from __future__ import annotations

import json
from typing import Iterable

from .utils import truncate_field


def build_snippet_item(
    doc_id: str,
    doc_meta: dict[str, str],
    fields: list[str],
    per_field_chars: dict[str, int],
) -> dict[str, str]:
    item = {"id": doc_id}
    for field in fields:
        value = doc_meta.get(field, "")
        limit = per_field_chars.get(field, len(value))
        item[field] = truncate_field(value, limit)
    return item


def cap_by_budget(items: Iterable[dict[str, str]], budget_bytes: int) -> tuple[list[dict[str, str]], int, bool]:
    acc: list[dict[str, str]] = []
    used = 0
    truncated = False
    for item in items:
        encoded = json.dumps(item, ensure_ascii=False).encode("utf-8")
        if used + len(encoded) > budget_bytes:
            truncated = True
            break
        acc.append(item)
        used += len(encoded)
    return acc, used, truncated


__all__ = ["build_snippet_item", "cap_by_budget"]
