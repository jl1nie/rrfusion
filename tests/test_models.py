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
        "app_id",
        "pub_id",
        "exam_id",
        "app_date",
        "pub_date",
        "apm_applicants",
        "cross_en_applicants",
        "ipc_codes",
        "cpc_codes",
        "fi_codes",
        "ft_codes",
    }


def test_peek_snippets_request_defaults() -> None:
    request = PeekSnippetsRequest(run_id="run-123")
    assert request.fields == [
        "title",
        "abst",
        "claim",
        "app_doc_id",
        "app_id",
        "pub_id",
        "exam_id",
        "app_date",
        "pub_date",
        "apm_applicants",
        "cross_en_applicants",
    ]
    assert request.per_field_chars == {
        "title": 80,
        "abst": 320,
        "claim": 320,
        "app_doc_id": 128,
        "app_id": 128,
        "pub_id": 128,
        "exam_id": 128,
        "app_date": 64,
        "pub_date": 64,
        "apm_applicants": 128,
        "cross_en_applicants": 128,
    }


def test_get_snippets_request_defaults() -> None:
    request = GetSnippetsRequest(ids=["doc-1"])
    assert request.fields == [
        "title",
        "abst",
        "claim",
        "desc",
        "app_doc_id",
        "app_id",
        "pub_id",
        "exam_id",
        "app_date",
        "pub_date",
        "apm_applicants",
        "cross_en_applicants",
        "ipc_codes",
        "cpc_codes",
        "fi_codes",
        "ft_codes",
    ]
    assert request.per_field_chars == {
        "title": 160,
        "abst": 480,
        "claim": 800,
        "desc": 800,
        "app_doc_id": 128,
        "app_id": 128,
        "pub_id": 128,
        "exam_id": 128,
        "app_date": 64,
        "pub_date": 64,
        "apm_applicants": 128,
        "cross_en_applicants": 128,
        "ipc_codes": 256,
        "cpc_codes": 256,
        "fi_codes": 256,
        "ft_codes": 256,
    }


def test_peek_config_defaults() -> None:
    config = PeekConfig()
    assert config.fields == ["title", "abst", "claim"]
    assert config.per_field_chars == {"title": 120, "abst": 360, "claim": 320}
