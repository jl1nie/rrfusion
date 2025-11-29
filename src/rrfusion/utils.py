"""Shared helpers for hashing queries, truncating text, and byte accounting."""

from __future__ import annotations

import hashlib
import json
import random
import string


def hash_query(query: str, filters: dict | None = None) -> str:
    payload = {"q": query, "filters": filters or {}}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def random_doc_id(rng: random.Random | None = None) -> str:
    rng = rng or random
    digits = "".join(rng.choice(string.digits) for _ in range(10))
    letter = rng.choice(string.ascii_uppercase)
    return f"JP{digits}{letter}"


def truncate_field(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    ellipsis = "..." if max_chars > 3 else ""
    slice_len = max_chars - len(ellipsis)
    return value[:slice_len] + ellipsis


def normalize_fi_subgroup(fi: str) -> str:
    """
    Normalize FI subgroup codes by stripping trailing edition symbols.

    Examples:
        "G06V10/82A" -> "G06V10/82"
        "H04L1/00" -> "H04L1/00" (unchanged)
    """
    code = (fi or "").strip()
    if not code:
        return ""
    code = code.upper()
    if len(code) > 1 and code[-1].isalpha() and code[-2].isdigit():
        return code[:-1]
    return code


__all__ = ["hash_query", "random_doc_id", "truncate_field", "normalize_fi_subgroup"]
