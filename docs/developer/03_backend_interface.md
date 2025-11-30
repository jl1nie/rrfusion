# バックエンドインターフェース

本章では、RRFusion MCPサーバとバックエンドシステムとの連携仕様を解説します。

## 1. バックエンド構成

### 必要なバックエンドシステム

**Patent Database:**
- 特許メタデータ（FI/F-Term、出願日、公開日等）
- 全文テキスト（title/abst/claim/desc）

**Fulltext Search Engine:**
- Boolean query対応
- field_boosts対応
- フィルタリング対応

**Semantic Search Engine:**
- vector embedding対応
- top-k検索

### 想定技術スタック

**Patent Database:**
- PostgreSQL / MySQL 等

**Fulltext Search:**
- Elasticsearch
- Solr
- 独自実装

**Semantic Search:**
- Vector database（Pinecone, Weaviate, Milvus等）
- Elasticsearch + dense_vector
- 独自実装

## 2. Fulltext検索インターフェース

### fulltext_search API

**エンドポイント:** `POST /api/fulltext_search`

**リクエスト:**
```python
{
  "query": str,                    # Boolean query
  "filters": List[Filter],         # フィルタ
  "top_k": int,                    # 取得上限
  "field_boosts": Dict[str, float] # フィールド別重み
}
```

**Filter:**
```python
{
  "lop": str,       # "and" | "or"
  "field": str,     # "fi" | "ft" | "country" | "date" | ...
  "op": str,        # "in" | ">=" | "<=" | "=" | ...
  "value": Any
}
```

**レスポンス:**
```python
{
  "hit_count": int,
  "results": List[SearchResult]
}
```

**SearchResult:**
```python
{
  "doc_id": str,       # 内部ID
  "score": float,      # スコア
  "pub_id": str,       # 公開番号
  "app_id": str,       # 出願番号
  "metadata": {
    "fi_norm": List[str],   # FIコード（正規化版）
    "fi_full": List[str],   # FIコード（edition symbol付き）
    "ft": List[str],        # F-Termコード
    "country": str,
    "date": str
  }
}
```

### フィールド指定

**サポートフィールド:**
- title: タイトル
- abst: 要約
- claim: クレーム
- desc: 明細書

**field_boosts実装:**
- Elasticsearchの場合: `multi_match` + `fields: ["title^80", "abst^10", ...]`
- Solrの場合: `qf` parameter

### Boolean query構文

**サポート演算子:**
- AND, OR, NOT
- フレーズマッチ: `"..."`
- ワイルドカード: `*`
- NEAR: `*N{n}"term1 term2"`, `*ONP{n}"term1 term2"`

**実装例（Elasticsearch）:**
```python
# Boolean query
{
  "query": {
    "query_string": {
      "query": query,
      "fields": [f"{field}^{boost}" for field, boost in field_boosts.items()]
    }
  }
}

# Filters
{
  "bool": {
    "filter": [
      {"terms": {"fi_norm": ["G06V10/82", "G06V40/16"]}} if field == "fi"
      # ...
    ]
  }
}
```

## 3. Semantic検索インターフェース

### semantic_search API

**エンドポイント:** `POST /api/semantic_search`

**リクエスト:**
```python
{
  "text": str,            # クエリテキスト
  "feature_scope": str,  # "wide" | "title_abst_claims" | ...
  "top_k": int
}
```

**レスポンス:**
```python
{
  "hit_count": int,
  "results": List[SearchResult]
}
```

**SearchResult:**
```python
{
  "doc_id": str,
  "score": float,  # cosine similarity等
  "pub_id": str,
  "app_id": str,
  "metadata": {...}
}
```

### feature_scopeの実装

**feature_scope:**
- wide: 全文（title + abst + claim + desc）
- title_abst_claims: title + abst + claim
- claims_only: claim only
- top_claim: independent claim only
- background_jp: 【背景技術】セクション（日本語）

**実装方法:**
- 各scopeに対応したvector indexを事前に構築
- または、クエリ時にフィルタリング

### Embeddingモデル

**想定:**
- 日本語対応のembeddingモデル
- 例: multilingual-e5, sonoisa/sentence-bert-base-ja-mean-tokens

## 4. Document取得インターフェース

### get_documents API

**エンドポイント:** `POST /api/get_documents`

**リクエスト:**
```python
{
  "doc_ids": List[str],  # 内部IDリスト
  "fields": List[str],   # 取得フィールド
  "per_field_chars": Optional[Dict[str, int]]  # フィールド別文字数上限
}
```

**レスポンス:**
```python
{
  "documents": List[Document]
}
```

**Document:**
```python
{
  "doc_id": str,
  "pub_id": str,
  "app_id": str,
  "title": str,
  "abst": str,
  "claim": str,
  "desc": str,
  "metadata": {
    "fi_norm": List[str],
    "fi_full": List[str],
    "ft": List[str],
    "filing_date": str,
    "publication_date": str,
    "applicant": str,
    "inventor": List[str]
  }
}
```

### per_field_chars処理

**目的:** スニペット長を制限

**実装:**
- 指定文字数で切り捨て
- できれば文境界で切る

**例:**
```python
per_field_chars = {"title": 160, "abst": 480, "claim": 320, "desc": 800}
```

## 5. Publication取得インターフェース

### get_publication_by_id API

**エンドポイント:** `POST /api/get_publication`

**リクエスト:**
```python
{
  "id": str,
  "id_type": str,   # "pub_id" | "app_doc_id" | "app_id" | "exam_id"
  "fields": List[str],
  "per_field_chars": Optional[Dict[str, int]]
}
```

**レスポンス:**
```python
Document  # 上記と同じ
```

### id_type対応

**pub_id（公開番号）:**
- 例: JP2023-123456A, JP2023-123456B, WO2023/123456

**app_doc_id（出願番号EPODOC形式）:**
- 例: JP2023123456

**app_id（出願番号ユーザ入力形式）:**
- 例: 特願2023-123456、特開2023-123456、特表2023-500001

**exam_id（審査番号）:**
- 例: 2023-123456

### JP番号の正規化

**日本特許番号の変換:**
- 特願2023-123456 → JP2023123456（app_doc_id）
- 特開2023-123456 → JP2023-123456A（pub_id）
- 特表2023-500001 → JP2023-500001A（pub_id）
- 再表2023/123456 → WO2023/123456（pub_id）

**実装:**
- バックエンド側で正規化処理を実装
- または、RRFusion MCP側で正規化してからバックエンドに渡す

## 6. fi_norm / fi_full の保存要件

### ストレージ要件

**両方を保存:**
- fi_norm: edition symbol除去版（例: G06V10/82）
- fi_full: edition symbol付き版（例: G06V10/82A）

**インデックス:**
- fi_norm: 検索・フィルタ用インデックス
- fi_full: メタデータとして保存（検索には使用しないがπ(d)計算で使用）

### データベーススキーマ例

**PostgreSQL:**
```sql
CREATE TABLE patents (
  doc_id VARCHAR PRIMARY KEY,
  pub_id VARCHAR,
  app_id VARCHAR,
  title TEXT,
  abst TEXT,
  claim TEXT,
  desc TEXT,
  fi_norm VARCHAR[],   -- FIコード（正規化版）
  fi_full VARCHAR[],   -- FIコード（edition symbol付き）
  ft VARCHAR[],        -- F-Termコード
  country VARCHAR,
  filing_date DATE,
  publication_date DATE
);

CREATE INDEX idx_fi_norm ON patents USING GIN(fi_norm);
```

**Elasticsearch:**
```json
{
  "mappings": {
    "properties": {
      "doc_id": {"type": "keyword"},
      "pub_id": {"type": "keyword"},
      "title": {"type": "text", "analyzer": "japanese"},
      "abst": {"type": "text", "analyzer": "japanese"},
      "claim": {"type": "text", "analyzer": "japanese"},
      "desc": {"type": "text", "analyzer": "japanese"},
      "fi_norm": {"type": "keyword"},
      "fi_full": {"type": "keyword"},
      "ft": {"type": "keyword"},
      "country": {"type": "keyword"},
      "publication_date": {"type": "date"}
    }
  }
}
```

## 7. パフォーマンス要件

### 想定レスポンスタイム

**fulltext_search:**
- < 1秒（top_k=500程度）

**semantic_search:**
- < 2秒（top_k=300程度）

**get_documents:**
- < 500ms（10-30件）

**get_publication:**
- < 200ms（1件）

### キャッシュ戦略

**検索結果キャッシュ:**
- 同一クエリの結果をキャッシュ（TTL: 1時間程度）

**Document キャッシュ:**
- 頻繁にアクセスされる文献をキャッシュ

## まとめ

バックエンドインターフェースの要点:

**必要なAPI:**
- fulltext_search
- semantic_search
- get_documents
- get_publication

**重要な実装要件:**
- fi_norm / fi_full の両方保存
- id_type対応（pub_id/app_doc_id/app_id/exam_id）
- per_field_chars処理
- Boolean query, NEAR演算子対応

次章では、ストレージ層仕様の詳細を学びます。
