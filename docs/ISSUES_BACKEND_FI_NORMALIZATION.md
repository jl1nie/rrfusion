# Issue: バックエンドでFIフィルタの自動正規化をサポート

## 概要

Patentfieldバックエンドが`fi`フィールドのフィルタで分冊識別記号付き（`fi_full`形式）のコードを受け取ると400エラーを返す。

## 現状の問題

### エラー再現
```json
// Request
{
  "filters": [{
    "field": "fi",
    "op": "in",
    "value": ["G06V10/82A", "G06V40/16A"]  // fi_full形式
  }]
}

// Response
400 Bad Request
```

### 根本原因
- `normalize_fi_subgroup`関数は存在する（[utils.py:34-48](../src/rrfusion/utils.py#L34-L48)）
- レスポンス処理では正規化を実施（[patentfield.py:150-158](../src/rrfusion/mcp/backends/patentfield.py#L150-L158)）
- **リクエスト処理で正規化していない**

## 期待される動作

バックエンドがLLMエージェントから`fi_full`形式を受け取った場合：

1. フィルタ値を自動正規化
   - `"G06V10/82A"` → `"G06V10/82"`
   - `"H04L1/00"` → `"H04L1/00"` (変更なし)

2. 正規化後のコードで検索実行

3. LLMは両形式を気にせず使用可能

## 提案される修正

### 修正箇所: `src/rrfusion/mcp/backends/patentfield.py`

```python
def _normalize_request_filters(self, filters: list[Cond]) -> list[Cond]:
    """
    Normalize FI codes in request filters before sending to Patentfield API.

    Handles both fi_norm (G06V10/82) and fi_full (G06V10/82A) formats.
    """
    from ...utils import normalize_fi_subgroup

    normalized_filters = []
    for filt in filters:
        if filt.get("field") == "fi" and filt.get("op") == "in":
            # Normalize FI codes
            original_values = filt.get("value", [])
            normalized_values = [
                normalize_fi_subgroup(code) for code in original_values
            ]
            # Remove duplicates while preserving order
            seen = set()
            unique_values = []
            for code in normalized_values:
                if code and code not in seen:
                    unique_values.append(code)
                    seen.add(code)

            normalized_filters.append({
                **filt,
                "value": unique_values
            })
        else:
            normalized_filters.append(filt)

    return normalized_filters
```

### 使用箇所

`search_fulltext`メソッド内で呼び出す：

```python
async def search_fulltext(self, params: SearchParams) -> SearchResult:
    # Normalize FI codes in filters
    normalized_filters = self._normalize_request_filters(params.filters or [])

    # Build Patentfield API request with normalized filters
    payload = {
        "query": params.query,
        "filters": normalized_filters,  # Use normalized version
        ...
    }
    ...
```

## テストケース

### ユニットテスト追加

```python
def test_normalize_request_filters_fi_codes():
    backend = PatentfieldBackend(...)

    filters = [
        {"lop": "and", "field": "fi", "op": "in",
         "value": ["G06V10/82A", "G06V40/16A", "H04L1/00"]},
        {"lop": "and", "field": "country", "op": "in", "value": ["JP"]}
    ]

    normalized = backend._normalize_request_filters(filters)

    # FI codes should be normalized
    assert normalized[0]["value"] == ["G06V10/82", "G06V40/16", "H04L1/00"]

    # Other filters unchanged
    assert normalized[1] == filters[1]

def test_normalize_request_filters_deduplication():
    backend = PatentfieldBackend(...)

    filters = [
        {"field": "fi", "op": "in",
         "value": ["G06V10/82A", "G06V10/82B", "G06V10/82"]}
    ]

    normalized = backend._normalize_request_filters(filters)

    # Should deduplicate to single normalized code
    assert normalized[0]["value"] == ["G06V10/82"]
```

### 統合テスト

```python
async def test_search_fulltext_accepts_fi_full():
    """Test that backend accepts fi_full format in filters."""
    backend = PatentfieldBackend(...)

    params = SearchParams(
        query="顔認証",
        filters=[
            {"lop": "and", "field": "fi", "op": "in",
             "value": ["G06V10/82A", "G06V40/16A"]}  # fi_full format
        ],
        top_k=10
    )

    # Should not raise 400 error
    result = await backend.search_fulltext(params)
    assert result.hit_count > 0
```

## 影響範囲

### 変更あり
- ✅ `src/rrfusion/mcp/backends/patentfield.py` - リクエストフィルタ正規化追加

### 変更不要（後方互換）
- ✅ `src/rrfusion/utils.py` - 既存の`normalize_fi_subgroup`を再利用
- ✅ MCP interface - APIシグネチャ変更なし
- ✅ SystemPrompt - LLMは両形式を使用可能になるが、既存動作は維持

## 優先度

**Medium** - 現状は回避策（fi_normのみ使用）で運用可能だが、LLMの混乱を減らすため修正推奨

## 関連ドキュメント

- [TROUBLESHOOTING_MCP_VALIDATION.md](TROUBLESHOOTING_MCP_VALIDATION.md#-問題-1-fi分冊識別記号をmustフィルタで使用バックエンド制限)
- [docs/developer/04_storage_layer.md](developer/04_storage_layer.md#fi_norm--fi_full-の実装)
- [docs/searcher/05_classification_codes.md](searcher/05_classification_codes.md#fi-edition-symbol分冊記号の扱い)

## チェックリスト

実装時の確認事項：

- [ ] `_normalize_request_filters`メソッドを実装
- [ ] `search_fulltext`で正規化を呼び出し
- [ ] ユニットテスト追加
- [ ] 統合テスト追加
- [ ] ドキュメント更新（TROUBLESHOOTING_MCP_VALIDATION.md）
- [ ] SystemPromptのポリシーを「推奨」から「両方サポート」に更新
- [ ] CIテストが通ることを確認

---

**作成日**: 2025-11-30
**ラベル**: `enhancement`, `backend`, `fi-codes`, `good-first-issue`
