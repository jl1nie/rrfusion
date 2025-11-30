# ストレージ層仕様

本章では、特許データの保存・検索に必要なストレージ層の実装要件を解説します。

## 1. データモデル

### Patent Document

```python
class PatentDocument:
    # 識別子
    doc_id: str              # 内部ID（一意）
    pub_id: str              # 公開番号（JP2023-123456A）
    app_id: str              # 出願番号（JP2023123456）

    # 全文フィールド
    title: str               # タイトル
    abst: str                # 要約（abstract）
    claim: str               # クレーム
    desc: str                # 明細書（description）

    # 分類コード
    fi_norm: List[str]       # FIコード（正規化版）
    fi_full: List[str]       # FIコード（edition symbol付き）
    ft: List[str]            # F-Termコード

    # メタデータ
    country: str             # 国コード（JP/US/EP/...）
    filing_date: date        # 出願日
    publication_date: date   # 公開日
    applicant: str           # 出願人
    inventor: List[str]      # 発明者
```

## 2. fi_norm / fi_full の実装

### 保存要件

**両方を保存:**
```python
fi_norm = ["G06V10/82", "G06V40/16"]          # edition symbol除去
fi_full = ["G06V10/82A", "G06V40/16B"]        # edition symbol付き
```

**用途:**
- fi_norm: Phase0 code_profiling, Phase2 全レーンでのフィルタ・ブースト
- fi_full: Phase1フィルタ、Phase2のπ(d)計算（secondary boost）

### 変換ロジック

**fi_full → fi_norm:**
```python
def normalize_fi(fi_full: str) -> str:
    """
    Remove edition symbol (last character if A-Z)
    G06V10/82A → G06V10/82
    """
    if fi_full and fi_full[-1].isalpha():
        return fi_full[:-1]
    return fi_full
```

**データロード時:**
```python
# 特許XMLまたはJSONからロード
fi_full_list = extract_fi_codes(patent_xml)  # ["G06V10/82A", "G06V40/16B"]
fi_norm_list = [normalize_fi(fi) for fi in fi_full_list]  # ["G06V10/82", "G06V40/16"]

# 両方を保存
doc.fi_full = fi_full_list
doc.fi_norm = fi_norm_list
```

## 3. インデックス構造

### PostgreSQL

```sql
CREATE TABLE patents (
  doc_id VARCHAR PRIMARY KEY,
  pub_id VARCHAR UNIQUE,
  app_id VARCHAR,
  title TEXT,
  abst TEXT,
  claim TEXT,
  desc TEXT,
  fi_norm VARCHAR[],
  fi_full VARCHAR[],
  ft VARCHAR[],
  country VARCHAR(2),
  filing_date DATE,
  publication_date DATE,
  applicant TEXT,
  inventor TEXT[]
);

-- インデックス
CREATE INDEX idx_pub_id ON patents(pub_id);
CREATE INDEX idx_app_id ON patents(app_id);
CREATE INDEX idx_fi_norm ON patents USING GIN(fi_norm);
CREATE INDEX idx_fi_full ON patents USING GIN(fi_full);
CREATE INDEX idx_ft ON patents USING GIN(ft);
CREATE INDEX idx_country ON patents(country);
CREATE INDEX idx_publication_date ON patents(publication_date);

-- Full-text search (PostgreSQL)
CREATE INDEX idx_title_fts ON patents USING GIN(to_tsvector('japanese', title));
CREATE INDEX idx_abst_fts ON patents USING GIN(to_tsvector('japanese', abst));
CREATE INDEX idx_claim_fts ON patents USING GIN(to_tsvector('japanese', claim));
CREATE INDEX idx_desc_fts ON patents USING GIN(to_tsvector('japanese', desc));
```

### Elasticsearch

```json
{
  "mappings": {
    "properties": {
      "doc_id": {"type": "keyword"},
      "pub_id": {"type": "keyword"},
      "app_id": {"type": "keyword"},
      "title": {"type": "text", "analyzer": "kuromoji"},
      "abst": {"type": "text", "analyzer": "kuromoji"},
      "claim": {"type": "text", "analyzer": "kuromoji"},
      "desc": {"type": "text", "analyzer": "kuromoji"},
      "fi_norm": {"type": "keyword"},
      "fi_full": {"type": "keyword"},
      "ft": {"type": "keyword"},
      "country": {"type": "keyword"},
      "filing_date": {"type": "date"},
      "publication_date": {"type": "date"},
      "applicant": {"type": "text", "analyzer": "kuromoji"},
      "inventor": {"type": "text", "analyzer": "kuromoji"}
    }
  }
}
```

## 4. field_boosts実装

### Elasticsearch

```python
def build_query(query: str, field_boosts: Dict[str, float]) -> dict:
    """
    Build Elasticsearch query with field_boosts
    """
    fields = [f"{field}^{boost}" for field, boost in field_boosts.items()]
    return {
        "query": {
            "query_string": {
                "query": query,
                "fields": fields
            }
        }
    }

# 例
field_boosts = {"title": 80, "abst": 10, "claim": 5, "desc": 1}
query = build_query("(顔認証 AND 遮蔽)", field_boosts)
# → {"query": {"query_string": {"query": "(顔認証 AND 遮蔽)", "fields": ["title^80", "abst^10", "claim^5", "desc^1"]}}}
```

### PostgreSQL

```python
def build_fts_query(query: str, field_boosts: Dict[str, float]) -> str:
    """
    Build PostgreSQL full-text search query with field_boosts
    """
    # PostgreSQLのtsvectorは重み付けが複雑
    # 簡易版: 各フィールドを別々にクエリして重み付けして合成
    parts = []
    for field, boost in field_boosts.items():
        parts.append(f"ts_rank(to_tsvector('japanese', {field}), query) * {boost}")

    score_expr = " + ".join(parts)
    return f"SELECT *, ({score_expr}) AS score FROM patents WHERE ..."
```

## 5. filters処理

### Filter構造

```python
class Filter:
    lop: str      # "and" | "or"
    field: str    # "fi" | "ft" | "country" | "date" | ...
    op: str       # "in" | ">=" | "<=" | "=" | ...
    value: Any    # 値
```

### Elasticsearch実装

```python
def build_filters(filters: List[Filter]) -> dict:
    """
    Build Elasticsearch bool query from filters
    """
    must = []
    should = []

    for f in filters:
        if f.op == "in":
            clause = {"terms": {f.field: f.value}}
        elif f.op == ">=":
            clause = {"range": {f.field: {"gte": f.value}}}
        elif f.op == "<=":
            clause = {"range": {f.field: {"lte": f.value}}}
        elif f.op == "=":
            clause = {"term": {f.field: f.value}}

        if f.lop == "and":
            must.append(clause)
        elif f.lop == "or":
            should.append(clause)

    return {
        "bool": {
            "must": must,
            "should": should,
            "minimum_should_match": 1 if should else 0
        }
    }

# 例
filters = [
    {"lop": "and", "field": "fi_norm", "op": "in", "value": ["G06V10/82", "G06V40/16"]},
    {"lop": "and", "field": "country", "op": "in", "value": ["JP"]},
    {"lop": "and", "field": "publication_date", "op": ">=", "value": "2015-01-01"}
]
# → {"bool": {"must": [{"terms": {"fi_norm": [...]}}, {"terms": {"country": [...]}}, {"range": {"publication_date": {"gte": "2015-01-01"}}}]}}
```

### PostgreSQL実装

```python
def build_where_clause(filters: List[Filter]) -> str:
    """
    Build PostgreSQL WHERE clause from filters
    """
    conditions = []
    for f in filters:
        if f.op == "in":
            values_str = ", ".join([f"'{v}'" for v in f.value])
            cond = f"{f.field} = ANY(ARRAY[{values_str}])"  # for array fields
        elif f.op == ">=":
            cond = f"{f.field} >= '{f.value}'"
        elif f.op == "<=":
            cond = f"{f.field} <= '{f.value}'"
        elif f.op == "=":
            cond = f"{f.field} = '{f.value}'"

        conditions.append((f.lop, cond))

    # Build WHERE clause
    where_parts = []
    for i, (lop, cond) in enumerate(conditions):
        if i == 0:
            where_parts.append(cond)
        else:
            where_parts.append(f"{lop.upper()} {cond}")

    return " ".join(where_parts)
```

## 6. NEAR演算子の実装

### Elasticsearch

**proximity search:**
```json
{
  "query": {
    "span_near": {
      "clauses": [
        {"span_multi": {"match": {"fuzzy": {"value": "遮蔽"}}}},
        {"span_multi": {"match": {"fuzzy": {"value": "特徴量"}}}}
      ],
      "slop": 30,
      "in_order": false
    }
  }
}
```

### Lucene query parser（Elasticsearchのquery_string）

**NEAR equivalent:**
```
"遮蔽 特徴量"~30
```
→ 30トークン以内に両方出現

**RRFusionのNEAR構文変換:**
```python
def convert_near_to_lucene(query: str) -> str:
    """
    Convert RRFusion NEAR syntax to Lucene proximity search
    *N30"(遮蔽 OR マスク) (特徴量)" → "遮蔽 特徴量"~30 OR "マスク 特徴量"~30
    """
    # 簡易版（実装は複雑）
    import re
    pattern = r'\*N(\d+)"([^"]+)"'
    matches = re.findall(pattern, query)

    for distance, terms in matches:
        # OR-groupを展開してproximity queryに変換
        # 実装省略
        pass

    return converted_query
```

## 7. per_field_chars処理

### スニペット生成

```python
def truncate_field(text: str, max_chars: int) -> str:
    """
    Truncate text to max_chars, preferably at sentence boundary
    """
    if len(text) <= max_chars:
        return text

    # 文境界で切る（簡易版）
    truncated = text[:max_chars]
    last_period = max(
        truncated.rfind('。'),
        truncated.rfind('. '),
        truncated.rfind('\n')
    )

    if last_period > max_chars * 0.8:  # 80%以上の位置なら文境界で切る
        return truncated[:last_period + 1]
    else:
        return truncated + "..."

def apply_per_field_chars(doc: dict, per_field_chars: Dict[str, int]) -> dict:
    """
    Apply per_field_chars to document
    """
    result = doc.copy()
    for field, max_chars in per_field_chars.items():
        if field in result:
            result[field] = truncate_field(result[field], max_chars)
    return result

# 例
per_field_chars = {"title": 160, "abst": 480, "claim": 320, "desc": 800}
snippet = apply_per_field_chars(doc, per_field_chars)
```

## まとめ

ストレージ層実装の要点:

**データモデル:**
- fi_norm / fi_full の両方保存
- 全文フィールド（title/abst/claim/desc）

**インデックス:**
- fi_norm: 検索・フィルタ用
- fi_full: メタデータ（π(d)計算用）
- Full-text index: Elasticsearch kuromoji / PostgreSQL to_tsvector

**機能実装:**
- field_boosts: Elasticsearch fields^boost / PostgreSQL weighted ranking
- filters: bool query / WHERE clause
- NEAR: span_near / proximity search
- per_field_chars: スニペット切り詰め

次章では、融合エンジン仕様を学びます。
