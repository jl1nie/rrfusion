# MCPバリデーションエラー対策ガイド

## 概要

LLMエージェントがRRFusion MCPツールを呼び出す際に発生する代表的なバリデーションエラーと対策をまとめます。

## 問題パターンと対策

### ❌ 問題 #1: rrf_search_fulltext_raw のパラメータ構造不一致

**エラー:**
```
Missing required argument: params
Unexpected keyword argument: query, filters, top_k, field_boosts
```

**原因:**
```json
{
  "query": "...",         // ❌ トップレベルで渡している
  "filters": [...],
  "top_k": 800,
  "field_boosts": {...}
}
```

**対策:**
```json
{
  "params": {  // ✅ paramsオブジェクトでラップ
    "query": "...",
    "filters": [...],
    "top_k": 800,
    "field_boosts": {...}
  }
}
```

**正しい呼び出し例:**
```json
{
  "tool_name": "rrf_search_fulltext_raw",
  "arguments": {
    "params": {
      "query": "(顔認証 OR 顔識別) AND (マスク OR 遮蔽)",
      "filters": [
        {"lop": "and", "field": "fi", "op": "in", "value": ["G06V10/82", "G06V40/16"]},
        {"lop": "and", "field": "country", "op": "in", "value": ["JP"]},
        {"lop": "and", "field": "pubyear", "op": "range", "value": [2015, 2024]}
      ],
      "top_k": 800,
      "field_boosts": {"title": 80, "abst": 10, "claim": 5, "desc": 1}
    }
  }
}
```

**重要な注意:**
- `rrf_search_fulltext_raw`と`rrf_search_semantic_raw`は`params`ラッパーが**必須**
- `run_multilane_search`は逆に`params`ラッパーが**不要**（問題#2参照）

---

### ❌ 問題 #2: run_multilane_search のパラメータ構造不一致

**エラー:**
```
Missing required argument: lanes
Unexpected keyword argument: params
```

**原因:**
```json
{
  "params": {  // ❌ paramsラッパー不要
    "lanes": [...]
  }
}
```

**対策:**
```json
{
  "lanes": [  // ✅ 直接lanesを渡す
    {
      "lane_name": "fulltext_recall",
      "tool": "search_fulltext",  // ✅ 必須
      "lane": "fulltext",          // ✅ 必須
      "params": {                  // ✅ 検索パラメータをparamsに格納
        "query": "...",
        "filters": [...],
        "top_k": 400,
        "field_boosts": {...}
      }
    }
  ]
}
```

**正しい呼び出し例:**
```json
{
  "tool_name": "run_multilane_search",
  "arguments": {
    "lanes": [
      {
        "lane_name": "fulltext_recall",
        "tool": "search_fulltext",
        "lane": "fulltext",
        "params": {
          "query": "(顔認証 OR 顔識別) AND (マスク OR 遮蔽)",
          "filters": [
            {"lop": "and", "field": "fi", "op": "in", "value": ["G06V10/82", "G06V40/16"]},
            {"lop": "and", "field": "country", "op": "in", "value": ["JP"]},
            {"lop": "and", "field": "pubyear", "op": "range", "value": [2015, 2024]}
          ],
          "top_k": 400,
          "field_boosts": {"title": 40, "abst": 10, "claim": 5, "desc": 4}
        }
      },
      {
        "lane_name": "semantic",
        "tool": "search_semantic",
        "lane": "semantic",
        "params": {
          "text": "顔認証において、マスク着用により口元が遮蔽された場合でも...",
          "feature_scope": "wide",
          "top_k": 300
        }
      }
    ]
  }
}
```

---

### ❌ 問題 #3: rrf_blend_frontier のパラメータ構造不一致

**エラー:**
```
Missing required argument: request
Unexpected keyword argument: runs, target_profile, rrf_k, beta_fuse
```

**原因:**
```json
{
  "runs": [...],           // ❌ トップレベルで渡している
  "target_profile": {...},
  "rrf_k": 60,
  "beta_fuse": 1.2
}
```

**対策:**
```json
{
  "request": {  // ✅ requestオブジェクトでラップ
    "runs": [
      {"lane": "fulltext", "run_id_lane": "fulltext-abc123"},
      {"lane": "semantic", "run_id_lane": "semantic-def456"}
    ],
    "target_profile": {
      "fi": {"G06V10/82": 1.0, "G06V40/16": 0.9},
      "ft": {}
    },
    "rrf_k": 60,
    "beta_fuse": 1.2
  }
}
```

**正しい呼び出し例:**
```json
{
  "tool_name": "rrf_blend_frontier",
  "arguments": {
    "request": {
      "runs": [
        {"lane": "fulltext", "run_id_lane": "fulltext-f9a5586b"},
        {"lane": "semantic", "run_id_lane": "semantic-abc12345"}
      ],
      "target_profile": {
        "fi": {
          "G06V10/82": 1.0,
          "G06V40/16": 0.95,
          "G06T7/00": 0.8
        },
        "ft": {}
      },
      "rrf_k": 60,
      "beta_fuse": 1.2,
      "facet_terms": {
        "A_terms": ["特徴抽出", "特徴量", "エンコーディング"],
        "B_terms": ["重み付け", "強調", "選択", "補完"]
      }
    }
  }
}
```

**重要な注意:**
- `runs`配列の各要素は`{lane: str, run_id_lane: str}`の形式
- ❌ `run_id`と`weight`を使わない
- ✅ `lane`と`run_id_lane`を使う

---

### ❌ 問題 #4: NEAR演算子の不正な構文

**エラー:**
```
400 Bad Request from backend
```

**原因:**
```
// ❌ 不正な構文
*N30"(マスク OR 遮蔽) (目元 OR 額)"
```

**対策:**
```
// ✅ 正しい構文（ANDで区切られた2つのグループ）
*N30"(マスク OR 遮蔽) AND (目元 OR 額)"

// または
*N30"マスク 目元"  // シンプルな2タームの近接検索
```

**NEAR演算子ルール:**
- `*N{distance}"term1 AND term2"`: term1とterm2が指定距離内に出現
- `*ONP{distance}"term1 AND term2"`: 順序付き近接検索（term1がterm2の前）
- 各グループは`AND`で接続（スペースだけでは不可）
- **NEARを使用する場合、クエリ全体を簡潔に保つ（4-5個のANDグループまで）**
- **複雑なクエリ（6個以上のANDグループ、複数のNOT）ではNEARを避ける**
- **NEAR演算子は1クエリにつき1-2箇所まで**

**原因3: 複雑すぎるクエリでNEARを使用**
```
// ❌ 複雑すぎる（6個のANDグループ + 2個のNOT + NEAR）
(顔認証) AND *N30"(マスク) AND (目元)" AND (検知) AND (特徴抽出) AND (強化) AND (認証) NOT (指紋) NOT (表情認識)
```

**対策:**
```
// ✅ シンプルに保つ（4-5個のANDグループまで）
(顔認証) AND *N30"(マスク) AND (目元)" AND (強化) AND (認証)

// または、NEARを外してシンプルなANDに変更
(顔認証) AND (マスク) AND (目元) AND (検知) AND (特徴抽出) AND (強化) AND (認証)
```

---

## クイックチェックリスト

LLMエージェントがMCPツールを呼び出す前に確認すべき項目:

### ✅ rrf_search_fulltext_raw / rrf_search_semantic_raw

- [ ] すべてのパラメータを`params`オブジェクトでラップ
- [ ] `params`内に`query`（fulltextの場合）または`text`（semanticの場合）
- [ ] `params`内に`filters`, `top_k`, `field_boosts`等を格納

### ✅ search_fulltext / search_semantic（詳細版）

- [ ] `fi`フィールドのフィルタは**fi_norm**（例: G06V10/82）または**fi_full**（例: G06V10/82A）のどちらでも可
- [ ] NEAR演算子の構文が正しい（`AND`で接続、スペースのみは不可）
- [ ] NEARを使用する場合、クエリ全体を簡潔に（4-5個のANDグループまで）
- [ ] 複雑なクエリ（6個以上のANDグループ、複数のNOT）ではNEARを使わない
- [ ] `pubyear`フィルタは`op: "range"`、`value: [start, end]`
- [ ] `field_boosts`の値が妥当（title: 40-80, abst: 10-20, claim: 5-40, desc: 4-40）

### ✅ run_multilane_search

- [ ] `lanes`配列を**トップレベル**で渡す（`params`ラッパー不要）
- [ ] 各レーンに`tool`, `lane`, `params`の3フィールドが存在
- [ ] `tool`は`"search_fulltext"`または`"search_semantic"`
- [ ] `lane`は`"fulltext"`または`"semantic"`
- [ ] `params`内に検索パラメータ（query/text, filters, top_k等）

### ✅ rrf_blend_frontier

- [ ] すべてのパラメータを`request`オブジェクトでラップ
- [ ] `runs`配列の各要素に`run_id`, `lane`, `weight`
- [ ] `target_profile`に`fi`と`ft`の両方（空でも可）
- [ ] `rrf_k`と`beta_fuse`を明示的に指定

### ✅ rrf_mutate_run

- [ ] `base_run_id`を指定
- [ ] `mutate_delta`内で変更したいパラメータのみ指定
- [ ] `weights`, `lane_weights`, `pi_weights`は部分更新可能

---

## デバッグ手順

### 1. エラーメッセージから問題を特定

| エラーメッセージ | 原因 | 対策 |
|----------------|------|------|
| `Missing required argument: params` | `rrf_search_*_raw`で`params`ラッパーなし | `params`オブジェクトでラップ |
| `Unexpected keyword argument: query/text` | `rrf_search_*_raw`でトップレベルに直接渡している | `params`内に格納 |
| `Missing required argument: lanes` | `run_multilane_search`で`params`ラッパーを使用 | `lanes`を直接トップレベルで渡す |
| `Missing required argument: request` | `rrf_blend_frontier`でパラメータを直接渡している | `request`オブジェクトでラップ |
| `Unexpected keyword argument: params` | 不要な`params`ラッパー（`run_multilane_search`等） | ラッパーを削除 |
| `Field required: tool` | レーン定義に`tool`フィールドがない | `tool: "search_fulltext"`等を追加 |
| `400 Bad Request` | バックエンドが拒否 | NEAR構文を確認（ANDで接続されているか） |

### 2. SystemPromptの該当セクションを確認

- **FI分冊識別記号**: `code_usage_policy.fi_edition_symbols`
- **NEAR演算子**: `query_language.operators.NEAR`
- **レーン設計**: `lanes_config` セクション
- **ツール呼び出し**: `tool_usage` セクション

### 3. AGENT.mdでMCPツールシグネチャを確認

- [AGENT.md](../AGENT.md) セクション 4-9 でツール定義を確認
- Pydanticモデル: [src/rrfusion/models.py](../src/rrfusion/models.py)

### 4. ログを確認

```bash
# MCP server logs
docker compose -f infra/compose.ci.yml logs rrfusion-mcp

# Backend API logs (if using Patentfield)
# Check backend response for detailed error messages
```

---

## 参考資料

- **[SystemPrompt v1.5](../prompts/SystemPrompt_v1_5.yaml)**: LLMエージェント動作仕様
- **[AGENT.md](../AGENT.md)**: MCP API reference
- **[docs/developer/02_mcp_interface.md](developer/02_mcp_interface.md)**: MCP interface specifications
- **[docs/searcher/03_query_design.md](searcher/03_query_design.md)**: Query design guide

---

**最終更新**: 2025-11-30
