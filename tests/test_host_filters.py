from __future__ import annotations

import pytest

from rrfusion.mcp import host


def test_normalize_filters_accepts_range_dict() -> None:
    raw_filters = [
        {"lop": "and", "field": "pubyear", "op": "range", "value": {"from": "2023-01-01", "to": "2023-12-31"}}
    ]
    normalized = host._normalize_filters(raw_filters)
    assert len(normalized) == 1
    cond = normalized[0]
    assert cond.op == "range"
    assert cond.value == ["2023-01-01", "2023-12-31"]


def test_normalize_filters_accepts_flat_date_list() -> None:
    raw_filters = [
        {"lop": "and", "field": "pubyear", "op": "range", "value": ["2022-01-01", "2022-12-31"]}
    ]
    normalized = host._normalize_filters(raw_filters)
    cond = normalized[0]
    assert cond.value == ["2022-01-01", "2022-12-31"]


def test_normalize_filters_normalizes_date_ints() -> None:
    raw_filters = [
        {"lop": "and", "field": "pubyear", "op": "range", "value": [20220101, 20221231]}
    ]
    normalized = host._normalize_filters(raw_filters)
    cond = normalized[0]
    assert cond.value == ["2022-01-01", "2022-12-31"]


def test_normalize_filters_raises_on_unexpected_type() -> None:
    with pytest.raises(RuntimeError):
        host._normalize_filters([42])  # type: ignore[arg-type]
