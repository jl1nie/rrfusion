# MCPインターフェース

本章では、RRFusion MCPサーバが公開するツール群の仕様を解説します。

## 1. MCP（Model Context Protocol）概要

MCPは、LLMがexternal toolsを呼び出すための標準プロトコルです。

**特徴:**
- JSON-RPC 2.0ベース
- ツールの発見（list_tools）
- ツールの呼び出し（call_tool）
- ストリーミング対応（オプション）

**RRFusionでの使用:**
- LLMエージェント（Claude等）がMCP Clientとして動作
- RRFusion MCPサーバがツールを公開
- SystemPromptがツール使用の指示を提供

## 2. 公開ツール一覧

### エージェント向けツール（LLMが使用）

#### search系

**rrf_search_fulltext_raw**
- fulltext検索の生実行
- Phase0 wide_search、Phase1 representativeで使用

**run_multilane_search**
- 複数レーンの一括実行
- Phase2で使用

#### fusion系

**rrf_blend_frontier**
- 複数検索結果のRRF融合

**rrf_mutate_run**
- 融合パラメータのチューニング（cheap_path）

#### diagnostics系

**get_provenance**
- コード分布、レーン貢献度、構造メトリクス取得

#### snippets系

**peek_snippets**
- 上位候補のクイックプレビュー

**get_snippets**
- 詳細スニペット取得

#### publication系

**get_publication**
- 個別公報の取得（番号指定）

#### representatives系

**register_representatives**
- 代表公報の登録（ランキング影響）

### 人間向けツール（LLMは使用しない）

**search_fulltext**
- 簡易fulltext検索
- 返り値: list[str]（IDリストのみ）

**search_semantic**
- 簡易semantic検索
- 返り値: list[str]（IDリストのみ）

**注:** LLMエージェントはこれらを使用しません。

## 3. ツール仕様詳細

### rrf_search_fulltext_raw

**目的:** fulltext検索の生実行

**パラメータ:**
```python
{
  "query": str,                    # Boolean query
  "filters": List[Filter],         # フィルタリスト
  "top_k": int,                    # 取得上限（デフォルト500）
  "field_boosts": Dict[str, float],# フィールド別重み
  "sort": Optional[str]            # ソート（デフォルトスコア順）
}
```

**Filter構造:**
```python
{
  "lop": str,       # "and" | "or"
  "field": str,     # "fi" | "ft" | "country" | "date" | ...
  "op": str,        # "in" | ">=" | "<=" | "=" | ...
  "value": Any      # 値（リストまたは単一値）
}
```

**返り値:**
```python
RunHandle {
  "run_id": str,
  "lane": "fulltext",
  "run_id_lane": str,
  "hit_count": int,
  "top_k": int,
  "meta": {
    "query": str,
    "filters": List[Filter],
    "field_boosts": Dict[str, float]
  }
}
```

**例:**
```json
{
  "query": "(顔認証 OR 顔識別) AND (遮蔽 OR マスク)",
  "filters": [
    {"lop": "and", "field": "fi", "op": "in", "value": ["G06V10/82", "G06V40/16"]},
    {"lop": "and", "field": "country", "op": "in", "value": ["JP"]}
  ],
  "top_k": 500,
  "field_boosts": {"title": 80, "abst": 10, "claim": 5, "desc": 1}
}
```

### run_multilane_search

**目的:** 複数レーンの一括実行

**パラメータ:**
```python
{
  "lanes": List[LaneConfig]
}
```

**LaneConfig:**
```python
{
  "lane_name": str,                # "fulltext_recall" | "fulltext_precision" | "semantic"
  # fulltext laneの場合:
  "query": str,
  "filters": List[Filter],
  "top_k": int,
  "field_boosts": Dict[str, float],
  # semantic laneの場合:
  "text": str,
  "feature_scope": str,            # "wide" | "title_abst_claims" | ...
  "top_k": int
}
```

**返り値:**
```python
List[RunHandle]  # 各レーンのRunHandle
```

**例:**
```json
{
  "lanes": [
    {
      "lane_name": "fulltext_recall",
      "query": "((顔認証 OR 顔識別) AND (遮蔽 OR マスク))",
      "filters": [{"lop": "and", "field": "fi", "op": "in", "value": ["G06V10/82", "G06V40/16"]}],
      "top_k": 400,
      "field_boosts": {"title": 40, "abst": 10, "claim": 5, "desc": 4}
    },
    {
      "lane_name": "semantic",
      "text": "顔認証技術において、マスク等により顔の一部が遮蔽されている場合...",
      "feature_scope": "wide",
      "top_k": 300
    }
  ]
}
```

### rrf_blend_frontier

**目的:** 複数検索結果のRRF融合

**パラメータ:**
```python
{
  "runs": List[BlendRunInput],           # 各runにlane/run_id_lane/weightを指定
  "target_profile": TargetProfile,       # コード重み
  "weights": Optional[Dict[str, float]], # code boost weights (code/code_secondary)
  "lane_weights": Optional[Dict[str, float]], # レーン種別の重み
  "pi_weights": Optional[Dict[str, float]],   # π(d)計算の重み
  "facet_terms": Optional[Dict[str, List[str]]], # A/B/C要素の用語
  "facet_weights": Optional[Dict[str, float]],   # facet重み
  "rrf_k": Optional[float],              # RRF定数（デフォルト60）
  "beta_fuse": Optional[float]           # ブースト強度（デフォルト1.2）
}
```

**BlendRunInput:**
```python
{
  "lane": Literal["fulltext", "semantic", "original_dense"],
  "run_id_lane": str,    # レーン検索結果のrun ID
  "weight": float = 1.0  # このrunの重み（デフォルト1.0）
}
```

**TargetProfile:**
```python
{
  "fi": Dict[str, float],   # FIコード → 重み
  "ft": Dict[str, float]    # F-Termコード → 重み
}
```

**返り値:**
```python
FusionResult {
  "run_id": str,
  "ranked_docs": List[RankedDoc],
  "metrics": StructuralMetrics,
  "params": FusionParams
}
```

**例:**
```json
{
  "runs": [
    {"lane": "fulltext", "run_id_lane": "recall-run-id", "weight": 1.0},
    {"lane": "fulltext", "run_id_lane": "precision-run-id", "weight": 0.8},
    {"lane": "semantic", "run_id_lane": "semantic-run-id", "weight": 1.2}
  ],
  "target_profile": {
    "fi": {"G06V10/82": 1.0, "G06V40/16": 0.9},
    "ft": {}
  },
  "weights": {"code": 0.3, "code_secondary": 0.0},
  "lane_weights": {"recall": 1.0, "precision": 1.0, "semantic": 0.8},
  "pi_weights": {"code": 0.4, "facet": 0.3, "lane": 0.3},
  "rrf_k": 60,
  "beta_fuse": 1.2
}
```

### rrf_mutate_run

**目的:** 融合パラメータのチューニング

**パラメータ:**
```python
{
  "base_run_id": str,               # ベースとなる融合結果ID
  "mutate_delta": MutateDelta       # 変更するパラメータ
}
```

**MutateDelta:**
```python
{
  "weights": Optional[Dict[str, float]],
  "lane_weights": Optional[Dict[str, float]],
  "pi_weights": Optional[Dict[str, float]],
  "rrf_k": Optional[float],
  "beta_fuse": Optional[float]
}
```

**重要:** MutateDeltaの値は**絶対値**（増分ではない）

**返り値:**
```python
FusionResult  # 新しい融合結果
```

**例:**
```json
{
  "base_run_id": "fusion-789",
  "mutate_delta": {
    "weights": {"semantic": 0.5},
    "beta_fuse": 0.9
  }
}
```

### get_provenance

**目的:** コード分布、レーン貢献度、構造メトリクス取得

**パラメータ:**
```python
{
  "run_id": str  # 融合結果IDまたは検索結果ID
}
```

**返り値:**
```python
Provenance {
  "run_id": str,
  "code_freqs": {
    "fi": Dict[str, int],   # FIコード → 出現頻度
    "ft": Dict[str, int]    # F-Termコード → 出現頻度
  },
  "lane_contributions": Optional[Dict[str, float]], # レーン別貢献度（融合結果のみ）
  "metrics": Optional[StructuralMetrics]            # 構造メトリクス（融合結果のみ）
}
```

**例:**
```json
{
  "run_id": "fusion-789",
  "code_freqs": {
    "fi": {"G06V10/82": 25, "G06V40/16": 18, "G06K9/00": 7},
    "ft": {"5B089AA01": 12, "5B089CA13": 8}
  },
  "lane_contributions": {
    "recall": 0.38,
    "precision": 0.42,
    "semantic": 0.20
  },
  "metrics": {
    "LAS": 0.45,
    "CCW": 0.62,
    "S_shape": 0.28,
    "F_struct": 0.52,
    "Fproxy": 0.54
  }
}
```

### peek_snippets

**目的:** 上位候補のクイックプレビュー

**パラメータ:**
```python
{
  "run_id": str,
  "limit": Optional[int],            # 件数上限（デフォルト30）
  "fields": Optional[List[str]],     # 取得フィールド（デフォルトtitle/abst/claim）
  "budget_bytes": Optional[int],     # バイト数上限
  "per_field_chars": Optional[Dict[str, int]]  # フィールド別文字数上限
}
```

**返り値:**
```python
Snippets {
  "run_id": str,
  "snippets": List[Snippet]
}
```

**Snippet:**
```python
{
  "rank": int,
  "pub_id": str,
  "app_id": Optional[str],
  "title": str,
  "abst": str,
  "claim": Optional[str],
  "desc": Optional[str],
  "score": float,
  "metadata": Dict  # FI/F-Term等
}
```

**例:**
```json
{
  "run_id": "fusion-789",
  "limit": 30,
  "fields": ["title", "abst", "claim"],
  "per_field_chars": {"title": 160, "abst": 480, "claim": 320}
}
```

### get_publication

**目的:** 個別公報の取得（番号指定）

**パラメータ:**
```python
{
  "id": str,        # 公報番号
  "id_type": str,   # "pub_id" | "app_doc_id" | "app_id" | "exam_id"
  "fields": Optional[List[str]],  # 取得フィールド
  "per_field_chars": Optional[Dict[str, int]]
}
```

**id_type:**
- pub_id: 公開番号（JP2023-123456A）
- app_doc_id: 出願番号EPODOC形式（JP2023123456）
- app_id: 出願番号ユーザ入力形式（特願2023-123456、特開2023-123456）
- exam_id: 審査番号

**返り値:**
```python
Publication {
  "pub_id": str,
  "app_id": str,
  "title": str,
  "abst": str,
  "claim": str,
  "desc": str,
  "metadata": Dict  # FI/F-Term、出願日、公開日等
}
```

### register_representatives

**目的:** 代表公報の登録（ランキング影響）

**パラメータ:**
```python
{
  "pub_ids": List[str],  # 代表公報の公開番号リスト
  "category": str        # "A" | "B" | "C"（カテゴリ）
}
```

**返り値:**
```python
{
  "registered_count": int,
  "category": str
}
```

**効果:**
- 登録された文献はπ(d)でブースト
- 融合スコアが上昇

## 4. エラーハンドリング

### エラーレスポンス

```python
{
  "error": {
    "code": str,      # エラーコード
    "message": str,   # エラーメッセージ
    "details": Optional[Dict]  # 詳細情報
  }
}
```

### 主要エラーコード

**INVALID_QUERY:**
- クエリ構文エラー

**FILTER_ERROR:**
- フィルタ構造エラー（lop欠落等）

**RUN_NOT_FOUND:**
- 指定されたrun_idが存在しない

**BACKEND_ERROR:**
- バックエンド検索エンジンエラー

**INVALID_PARAMETER:**
- パラメータ範囲外（例: top_k < 0）

## 5. レート制限

**MVP段階:**
- 特に制限なし（社内利用想定）

**将来の拡張:**
- ユーザ単位でのレート制限
- 同時実行数制限

## まとめ

RRFusion MCPインターフェースは、以下のツールを公開します:

**エージェント向け:**
- search系: rrf_search_fulltext_raw, run_multilane_search
- fusion系: rrf_blend_frontier, rrf_mutate_run
- diagnostics系: get_provenance
- snippets系: peek_snippets, get_snippets
- publication系: get_publication
- representatives系: register_representatives

**返り値構造:**
- RunHandle, FusionResult, Provenance, Snippets, Publication

次章では、バックエンドインターフェースを学びます。
