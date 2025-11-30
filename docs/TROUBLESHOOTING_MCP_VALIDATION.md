# MCPバリデーションエラー対策ガイド

## 概要

LLMエージェントがRRFusion MCPツールを呼び出す際に発生する代表的なバリデーションエラーと対策をまとめます。

## 問題パターンと対策

### ❌ 問題 #1: FI分冊識別記号をMUSTフィルタで使用（バックエンド制限）

**エラー:**
```
400 Bad Request from backend
```

**原因:**
```json
{
  "filters": [{
    "field": "fi",
    "op": "in",
    "value": ["G06V10/82A", "G06V40/16A"]  // ⚠️ 分冊識別記号付き
  }]
}
```

**現状の対策（回避策）:**
```json
{
  "filters": [{
    "field": "fi",
    "op": "in",
    "value": ["G06V10/82", "G06V40/16"]  // ✅ fi_norm（正規化版）を使用
  }]
}
```

**⚠️ 重要な注意:**

これは**バックエンド実装の制限**であり、本来は実装バグです：

- ✅ **理想的な実装**: バックエンドが`fi_full`を受け取ったら内部で正規化して検索すべき
  - `normalize_fi_subgroup`関数は既に存在（[utils.py:34](../src/rrfusion/utils.py#L34)）
  - レスポンス側では正規化済み（[patentfield.py:154](../src/rrfusion/mcp/backends/patentfield.py#L154)）
  - **リクエスト側のフィルタ正規化が未実装**

- ❌ **現状**: Patentfieldバックエンドが`fi_full`形式を拒否

- 🔧 **修正予定**: `patentfield.py`でリクエスト時にフィルタを正規化する処理を追加

**SystemPromptの推奨ルール（暫定）:**
- `code_usage_policy.fi_edition_symbols`: "Avoid in MUST filters for backend compatibility"
- Phase2では**fi_normのみ**をフィルタに使用することを推奨（現状の回避策として）

**将来の実装:**
バックエンドでフィルタ正規化を実装後、LLMは両方の形式を安全に使用可能になる予定。

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
      {"run_id": "fulltext-abc123", "lane": "fulltext", "weight": 1.0},
      {"run_id": "semantic-def456", "lane": "semantic", "weight": 0.8}
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
        {"run_id": "fulltext-f9a5586b", "lane": "fulltext", "weight": 1.0},
        {"run_id": "semantic-abc12345", "lane": "semantic", "weight": 0.8}
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

---

## クイックチェックリスト

LLMエージェントがMCPツールを呼び出す前に確認すべき項目:

### ✅ rrf_search_fulltext_raw / search_fulltext

- [ ] `fi`フィールドのフィルタは**fi_norm**（分冊識別記号なし）
- [ ] NEAR演算子の構文が正しい（`AND`で接続）
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
| `Missing required argument: lanes` | `params`ラッパーを使用 | `lanes`を直接トップレベルで渡す |
| `Missing required argument: request` | パラメータを直接渡している | `request`オブジェクトでラップ |
| `Unexpected keyword argument: params` | 不要な`params`ラッパー | ラッパーを削除 |
| `Field required: tool` | レーン定義に`tool`フィールドがない | `tool: "search_fulltext"`等を追加 |
| `400 Bad Request` | バックエンドが拒否 | FI分冊識別記号、NEAR構文を確認 |

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
