"""Regression guards for the snippet-related Pydantic models."""

from typing import get_args

from rrfusion.models import (
    GetSnippetsRequest,
    PeekConfig,
    PeekSnippetsRequest,
    SnippetField,
)


def test_snippet_field_literal_contains_expected_values() -> None:
    assert set(get_args(SnippetField)) == {
        "title",
        "abst",
        "claim",
        "desc",
        "app_doc_id",
        "pub_id",
        "exam_id",
    }


def test_peek_snippets_request_defaults() -> None:
    request = PeekSnippetsRequest(run_id="run-123")
    assert request.fields == ["title", "abst", "claim"]
    assert request.per_field_chars == {"title": 160, "abst": 480, "claim": 320}


def test_get_snippets_request_defaults() -> None:
    request = GetSnippetsRequest(ids=["doc-1"])
    assert request.fields == ["title", "abst", "claim"]
    assert request.per_field_chars == {"title": 160, "abst": 480, "claim": 320}


def test_peek_config_defaults() -> None:
    config = PeekConfig()
    assert config.fields == ["title", "abst", "claim"]
    assert config.per_field_chars == {"title": 120, "abst": 360, "claim": 320}
