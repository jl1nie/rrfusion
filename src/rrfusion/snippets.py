"""Helpers for peek/get snippet shaping."""

from __future__ import annotations

import json
from typing import Iterable

from .utils import truncate_field

IDENTIFIER_FIELDS = ("app_doc_id", "app_id", "pub_id")


def build_snippet_item(
    doc_id: str,
    doc_meta: dict[str, str],
    fields: list[str],
    per_field_chars: dict[str, int],
) -> dict[str, str]:
    # Always include identifier fields in addition to any requested fields.
    effective_fields: list[str] = list(fields)
    for id_field in IDENTIFIER_FIELDS:
        if id_field not in effective_fields:
            effective_fields.append(id_field)

    item = {"id": doc_id}
    for field in effective_fields:
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
