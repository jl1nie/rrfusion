# システムアーキテクチャ

## 1. 3層アーキテクチャ

RRFusionは、以下の3層で構成されます。

```
┌─────────────────────────────────┐
│  LLMエージェント                  │
│  - Claude等のLLM                 │
│  - MCP Client                   │
│  - SystemPrompt解釈・実行        │
└────────────┬────────────────────┘
             │ MCP (Model Context Protocol)
             │
┌────────────┴────────────────────┐
│  RRFusion MCP Server            │
│  ┌───────────────────────────┐  │
│  │ MCP Tools                 │  │
│  │ - search系ツール          │  │
│  │ - fusion系ツール          │  │
│  │ - snippet系ツール         │  │
│  └───────────┬───────────────┘  │
│              │                   │
│  ┌───────────┴───────────────┐  │
│  │ Fusion Engine             │  │
│  │ - RRF計算                 │  │
│  │ - π(d)ブースト            │  │
│  │ - 構造メトリクス計算      │  │
│  └───────────┬───────────────┘  │
└──────────────┼───────────────────┘
               │ Backend API
               │
┌──────────────┴───────────────────┐
│  Backend Systems                 │
│  ┌───────────────────────────┐   │
│  │ Patent Database           │   │
│  │ - Metadata (FI/F-Term)    │   │
│  │ - Full-text               │   │
│  └────────────┬──────────────┘   │
│               │                  │
│  ┌────────────┴──────────────┐   │
│  │ Search Engines            │   │
│  │ - Fulltext (Elasticsearch)│   │
│  │ - Semantic (Vector DB)    │   │
│  └───────────────────────────┘   │
└──────────────────────────────────┘
```

### Layer 1: LLMエージェント

**役割:**
- SystemPromptに基づいて検索戦略を立案
- MCPツールを呼び出し
- 検索結果を人間向けに整形・提示
- ユーザとの対話（user_confirmation_protocol）

**実装例:**
- Claude + Claude Desktop（MCP Client内蔵）
- OpenAI + custom MCP client

### Layer 2: RRFusion MCP Server

**役割:**
- MCPプロトコルでツールを公開
- 複数検索結果の融合（RRF + π(d)ブースト）
- 構造メトリクス計算（LAS/CCW/Fproxy）
- 検索パラメータのチューニング（rrf_mutate_run）

**主要コンポーネント:**
- MCP Tools: MCPインターフェース
- Fusion Engine: RRF融合ロジック
- Metrics Calculator: 構造メトリクス計算

### Layer 3: Backend Systems

**役割:**
- 特許データの保存・管理
- fulltext検索実行
- semantic検索実行

**主要コンポーネント:**
- Patent Database: FI/F-Term等のメタデータ、全文
- Fulltext Search Engine: Elasticsearch等
- Semantic Search Engine: Vector database

## 2. コンポーネント間の依存関係

### LLMエージェント → RRFusion MCP

**プロトコル:** MCP（Model Context Protocol）

**依存:**
- LLMエージェントはRRFusion MCPのツール仕様に依存
- SystemPrompt YAMLがインターフェース契約

**データフロー:**
```
LLM → rrf_search_fulltext_raw(query, filters, ...)
    ← RunHandle {run_id, meta}

LLM → rrf_blend_frontier(runs, target_profile, ...)
    ← FusionResult {run_id, ranked_docs, metrics}

LLM → peek_snippets(run_id, limit, ...)
    ← Snippets [{pub_id, title, abst, ...}]
```

### RRFusion MCP → Backend Systems

**プロトコル:** REST API / gRPC / DB接続等（実装依存）

**依存:**
- RRFusion MCPはバックエンドの検索APIに依存
- fi_norm/fi_fullの両方を取得可能である必要

**データフロー:**
```
MCP → Backend: fulltext_search(query, filters, top_k)
    ← Search Results [{doc_id, score, metadata}]

MCP → Backend: semantic_search(text, feature_scope, top_k)
    ← Search Results [{doc_id, score, metadata}]

MCP → Backend: get_document(doc_id, fields)
    ← Document {pub_id, title, abst, claim, desc, fi_norm, fi_full, ...}
```

## 3. MVPとしての位置づけ

### 設計方針

**MVP（Minimum Viable Product）:**
- 実務検証を目的としたプロトタイプ
- 完全な自動化ではなく、人間との協調
- 継続的な改善を前提

**人手との協調:**
- LLMエージェントが検索戦略を立案
- 人間（サーチャー）が最終レビュー
- SystemPrompt YAMLを人間が継続的に改善

### 制約

**現時点の制約:**
- バックエンドシステムは既存のものを想定（新規構築しない）
- スケーラビリティは考慮するが、最優先ではない
- エラーハンドリングは基本的なもののみ

**今後の拡張可能性:**
- バックエンドの置き換え可能性を考慮
- MCPインターフェースは安定版として維持
- Fusion Engineの精緻化

### スケーラビリティ

**想定負荷:**
- 同時ユーザ: 1-10人
- 検索頻度: 1ユーザあたり数回/日
- 1検索あたりのレーン数: 3-5

**ボトルネック:**
- Backend fulltext/semantic検索
- LLM推論（feature_extraction, vocabulary_feedback）

**対策（将来）:**
- Backend検索結果のキャッシュ
- LLM推論のバッチ化
- 並列実行の最適化

## 4. システムフロー（Phase0/1/2）

### Phase0: Feature Extraction & Profiling

```
[LLMエージェント]
  ├─ feature_extraction（LLM推論）
  │   └─ A/A'/A''/B/C要素抽出
  │
  ├─ rrf_search_fulltext_raw("wide_search", ...)
  │   └→ [MCP] → [Backend] fulltext_search
  │      ← RunHandle {run_id: "wide-123"}
  │
  └─ get_provenance(run_id: "wide-123")
      └→ [MCP] Fusion Engine
         ├─ code分布分析
         └← target_profile {fi: {...}, ft: {...}}
```

### Phase1: Representative Hunting

```
[LLMエージェント]
  ├─ rrf_search_fulltext_raw("precision", fi_full使用可, ...)
  │   └→ [MCP] → [Backend] fulltext_search
  │      ← RunHandle {run_id: "rep-456"}
  │
  ├─ peek_snippets(run_id: "rep-456", count: 20-30)
  │   └→ [MCP] → [Backend] get_documents
  │      ← Snippets [{pub_id, title, abst, claim}]
  │
  └─ vocabulary_feedback（LLM推論）
      ├─ A/A'/A''/B/S要素抽出
      └─ synonym_cluster更新
```

### Phase2: Batch Retrieval

```
[LLMエージェント]
  ├─ run_multilane_search([recall_config, precision_config, semantic_config])
  │   └→ [MCP]
  │      ├→ [Backend] fulltext_search("recall")
  │      ├→ [Backend] fulltext_search("precision")
  │      ├→ [Backend] semantic_search(HyDE_text)
  │      └← [RunHandle, RunHandle, RunHandle]
  │
  ├─ rrf_blend_frontier(runs: [...], target_profile, weights, ...)
  │   └→ [MCP] Fusion Engine
  │      ├─ RRF計算
  │      ├─ π(d)ブースト
  │      ├─ 構造メトリクス計算
  │      └← FusionResult {run_id: "fusion-789", ranked_docs, metrics}
  │
  ├─ get_provenance(run_id: "fusion-789")
  │   └→ [MCP]
  │      └← Provenance {code_freqs, lane_contributions, metrics}
  │
  └─ peek_snippets(run_id: "fusion-789", limit: 30)
      └→ [MCP] → [Backend] get_documents
         └← Snippets [...]
```

### Tuning Loop（cheap_path）

```
[LLMエージェント]
  └─ rrf_mutate_run(base_run_id: "fusion-789", mutate_delta: {...})
      └→ [MCP] Fusion Engine
         ├─ 既存のレーン結果を再利用
         ├─ パラメータのみ変更して再融合
         └← FusionResult {run_id: "fusion-790", ...}
```

## 5. データモデル

### RunHandle

```python
class RunHandle:
    run_id: str           # 実行ID（一意）
    lane: str             # レーン名（"fulltext" / "semantic" / "code"）
    run_id_lane: str      # レーン内でのID
    hit_count: int        # ヒット件数
    top_k: int            # 取得上限
    meta: dict            # メタ情報（クエリ、フィルタ等）
```

### BlendRunInput

```python
class BlendRunInput:
    lane: str             # レーン名（"fulltext" / "semantic" / "original_dense"）
    run_id_lane: str      # レーン内でのrun ID
    weight: float = 1.0   # このrunの重み（デフォルト1.0）
```

**用途:** `rrf_blend_frontier` で複数のレーン結果を融合する際、各 run の重みを個別に指定可能。同じ lane を複数回使う場合（例: fulltext_recall と fulltext_precision）でも、それぞれ異なる重みを設定できる。

### FusionResult

```python
class FusionResult:
    run_id: str                  # 融合結果ID
    ranked_docs: List[RankedDoc] # ランク付き文献リスト
    metrics: StructuralMetrics   # 構造メトリクス
    params: FusionParams         # 融合パラメータ
```

### RankedDoc

```python
class RankedDoc:
    rank: int             # 順位（1-indexed）
    doc_id: str           # 文献ID（内部ID）
    pub_id: str           # 公開番号
    app_id: str           # 出願番号（オプション）
    score: float          # 融合スコア
    lane_scores: dict     # レーン別スコア
    metadata: dict        # メタデータ（FI/F-Term等）
```

### StructuralMetrics

```python
class StructuralMetrics:
    LAS: float       # Lane Agreement Score
    CCW: float       # Class Consistency Weight
    S_shape: float   # Score-Shape Index
    F_struct: float  # Structural F-score
    Fproxy: float    # Fusion Proxy Score
```

### TargetProfile

```python
class TargetProfile:
    fi: Dict[str, float]   # FIコード → 重み
    ft: Dict[str, float]   # F-Termコード → 重み
```

## 6. セキュリティとアクセス制御

### 想定セキュリティモデル

**MVP段階:**
- 社内ネットワーク内での使用を想定
- 基本的な認証（API key等）
- HTTPSによる通信暗号化

**将来の拡張:**
- ユーザ認証・認可（OAuth2等）
- アクセスログの記録
- レート制限

### データプライバシー

**特許データ:**
- 公開データのため、機密性は低い
- ただし、検索履歴はユーザのノウハウを含む → 保護が必要

**ログ:**
- クエリ、フィルタ、検索結果はログに記録
- 個人情報は含まれない想定

## まとめ

RRFusionは、3層アーキテクチャで構成されるMVPシステムです。

**核心:**
- LLMエージェントがSystemPromptに基づいて検索戦略を立案
- RRFusion MCPが複数検索結果を融合
- Backendが実際の検索を実行

**MVPとしての方針:**
- 人手との協調を前提
- 継続的な改善
- スケーラビリティは段階的に対応

次章では、MCPインターフェースの詳細を学びます。
