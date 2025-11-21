from __future__ import annotations

import pytest

from rrfusion.mcp import host


def test_filter_entry_generates_cond_list() -> None:
    raw_filter = {
        "field": "fi",
        "include_codes": ["H04L1/00"],
        "exclude_codes": ["H04L1/06"],
    }
    filters = host._normalize_filters([raw_filter])
    assert len(filters) == 2
    codes = [cond.value for cond in filters]
    assert ["H04L1/00"] in codes
    assert ["H04L1/06"] in codes


def test_filter_entry_handles_ranges() -> None:
    raw_filter = {
        "field": "pubyear",
        "include_range": {"from": "2020-01-01", "to": "2020-12-31"},
    }
    filters = host._normalize_filters([raw_filter])
    assert filters[0].op == "range"
    assert filters[0].value == ["2020-01-01", "2020-12-31"]


def test_filter_entry_raises_with_invalid_type() -> None:
    with pytest.raises(RuntimeError):
        host._normalize_filters([42])  # type: ignore[arg-type]
