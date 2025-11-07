from rrfusion.snippets import build_snippet_item, cap_by_budget


def test_build_snippet_item_truncates_fields():
    doc_meta = {"title": "abcdef", "abst": "z" * 500}
    item = build_snippet_item("123", doc_meta, ["title", "abst"], {"title": 3, "abst": 10})
    assert len(item["title"]) == 3
    assert len(item["abst"]) <= 10


def test_cap_by_budget_truncates_when_limit_hit():
    items = [{"id": "1", "title": "abc"} for _ in range(10)]
    capped, used, truncated = cap_by_budget(items, budget_bytes=30)
    assert truncated is True
    assert used <= 30
    assert capped
