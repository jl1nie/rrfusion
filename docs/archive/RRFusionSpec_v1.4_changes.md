# RRFusion MCP v1.4 変更点サマリー

このドキュメントは、v1.3からv1.4への主要な変更点をまとめたものです。
完全な仕様は [RRFusionSpecification.md](RRFusionSpecification.md) を参照してください。

---

## v1.4の主要変更点

### 1. Phase1/Phase2の完全分離

**v1.3までの問題**:
- code_profilingで絞りすぎて代表公報が拾えない
- 最初から本番検索を実行してしまい、語彙の精度が低い

**v1.4での解決**:
```
Phase0 (プロファイリング)
  └→ wide_search: 広く拾ってコード分布を把握
  └→ code_profiling: fi_normのみでtarget_profile生成

Phase1 (代表公報探索) ★NEW★
  └→ fulltext_precision のみ使用
  └→ 20-50件の高品質な代表公報を取得
  └→ edition symbol (fi_full) 使用可
  └→ 代表公報から語彙抽出: A/B/C/S要素

Phase2 (バッチ検索)
  └→ Phase1の語彙で全レーン再構築
  └→ recall + precision + semantic を run_multilane_search で一括実行
  └→ edition symbol禁止 (fi_normのみ)
  └→ semantic: HyDE必須
```

### 2. FI edition symbol（分冊識別記号）の使い分け明確化

**Phase0 (code_profiling)**:
- `fi_norm` のみ使用（サブグループレベル）
- edition symbol (A/B/C等) は使用しない
- 例: `G06V10/82`（分冊記号なし）

**Phase1 (representative_hunting)**:
- `fi_full` 使用可（edition symbol付き）
- MUST filterで使用可
- 例: `G06V10/82A`, `G06V10/82B`
- 目的: 高精度で代表公報を絞り込む

**Phase2 (batch_retrieval)**:
- `fi_norm` のみ使用（fi_fullは禁止）
- edition symbolはMUST filterで使用不可
- 例: `G06V10/82`（分冊記号なし）
- 目的: recall確保（edition symbolは割り当てが不安定でrecall低下の原因）

**実装要件**:
- ストレージ層: `fi_norm` と `fi_full` の両方を保存
- 融合層: 2段階ブースト
  - Primary boost: `fi_norm`（主要なコード認識ブースト）
  - Secondary boost: `fi_full`（弱いランキングヒント）

### 3. semantic レーンのHyDE必須化

**v1.3までの問題**:
- semantic laneにraw user textを投げると、用途語や曖昧語でdrift（暴走）しやすい
- 概念的に関連するが技術的には無関係な文献を拾いやすい

**v1.4での解決**:

**Phase0 (wide_search)**:
- semantic含める場合: raw user text可

**Phase1**:
- semantic laneは使用しない（fulltext_precision のみ）

**Phase2 (batch_retrieval)**:
- **HyDE必須**: Phase1の代表公報から抽出したA/B/S要素で自然言語サマリーを生成
- raw user textは禁止
- keyword listも禁止
- 1-3段落の自然言語パラグラフ

**HyDE生成例**:
```
顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
ゲートや入退室管理などの用途で使用される。
```

### 4. query_construction_policyの統合

**v1.3までの問題**:
- Boolean構文、wildcard、NEAR、A/B/C分解、FI/FT扱いが分散して記述されていた
- "良い検索式／悪い検索式"が曖昧

**v1.4での解決**:
- `query_construction_policy` セクションを新設（SystemPrompt.yaml）
- 以下を統合:
  - syntax: Boolean ops, phrase, wildcards, NEAR, field_boosts
  - term_roles: A/B/C要素の定義と使い方
  - classification: FI subgroup, edition symbol, F-Term usage
  - phase_rules: Phase1/Phase2のクエリ原則
  - semantic_rules: HyDE要件
  - examples: good/bad examples（レーン別）

### 5. レーン別good/bad examplesの追加

**fulltext_recall**:
```yaml
good:
  - query: "((顔認証 OR 顔識別) OR (バイオメトリクス)) AND (照合 OR 認証)"
    filters: [{field: "fi_norm", op: "in", value: ["G06V10/82", "G06V40/16"]}]
    notes: "広いOR-groups、複数FIコード"

bad:
  - query: "顔認証 AND ゲート AND 入退室管理"
    reason: "用途語(ゲート/入退室)をANDで縛りすぎ→recall低下"
```

**fulltext_precision**:
```yaml
good:
  - query: "(顔認証) AND (プライバシー保護) AND (ゲート OR 入退室)"
    filters: [{field: "fi_norm", op: "in", value: ["G06V10/82"]}]
    notes: "A+B MUST、C SHOULD"

bad:
  - query: "顔認証 AND ゲート AND 入退室管理 AND 車載"
    reason: "複数用途語をANDで縛ると、別用途の関連技術を見逃す"
```

**semantic**:
```yaml
good:
  - text: "顔認証技術において、カメラ映像から顔特徴を抽出し..."
    notes: "Phase1のA/B/S要素から生成した自然言語パラグラフ"

bad:
  - text: "顔認証 ゲート 入退室管理 プライバシー保護"
    reason: "keyword list、自然言語パラグラフではない"
  - text: "ゲートで使える顔認証技術が欲しいです。"
    reason: "Phase2でraw user text使用（HyDE必須）"
```

### 6. run_multilane_searchの活用

**v1.3までの問題**:
- Phase2でrecall/precision/semanticを個別に実行するとMCP呼び出し回数が増える

**v1.4での解決**:
- Phase2初回実行時、`run_multilane_search` で一括実行
- recall, precision, semanticを順次実行（1回のMCP呼び出し）
- rate limit対策

### 7. F-proxyの位置づけ明確化

**v1.3までの誤解**:
- F-proxy（構造メトリクス）をhard filterとして使う

**v1.4での明確化**:
- F-proxy（LAS/CCW/MAA）は**診断信号**
- Hard filterではない
- 値が低い場合の対応:
  - `rrf_mutate_run` でパラメータ調整（cheap path）
  - それでも解決しない場合のみ新レーン追加

**健全性基準**:
- `Fproxy >= 0.5`: 健全
- `Fproxy < 0.5`: チューニング推奨

### 8. presentation_policyのmode別整理

**production mode**:
- Researcher persona
- 高レベルな検索戦略のみ説明
- 内部パラメータ・レーン名は出さない

**debug mode**:
- System-prompt開発者向け
- レーン名、クエリ、パラメータを詳細に出力
- 次の1-2ステップとcoverage/precision問題に焦点

**internal_pro mode**:
- 社内専門サーチャー向け
- 検索式構造、FIコード、各トラックの貢献を日本語で説明
- 低レベル実装詳細は避ける

---

## MCPツール仕様の変更

### 新規/変更なし

v1.4ではMCPツールのインターフェース自体に変更はありません。
SystemPrompt側の使い方が変わっただけです。

**主要MCPツール**:
- `search_fulltext`: fulltext検索
- `search_semantic`: semantic検索
- `run_multilane_search`: 複数レーン一括実行
- `rrf_blend_frontier`: RRF融合
- `peek_snippets`: スニペット取得
- `get_publication`: 個別公報取得
- `get_provenance`: fusion recipe + 構造メトリクス取得
- `rrf_mutate_run`: パラメータ調整（cheap path）

**id_type対応**:
- `pub_id`: 公開番号
- `app_doc_id`: 出願番号（EPODOC形式）
- `app_id`: 出願番号（ユーザー入力形式、特願/特開含む）
- `exam_id`: 審査番号

**per_field_chars対応**:
- `peek_snippets`: デフォルト {title: 160, abst: 480, claim: 320}
- `get_publication`: デフォルト {title: 256, abst: 1500, claim: 1600, desc: 6000}

---

## A/B/C要素の扱いの明確化

### A要素（Core technical mechanisms）
- **定義**: 本質的な構成要素・コア技術
- **Phase1**: MUST
- **Phase2 recall**: SHOULD-weighted（SHOULDだがrecall重視）
- **Phase2 precision**: MUST

**例**: "顔認証アルゴリズム", "冷却構造", "センサ構成"

### B要素（Constraints / secondary conditions）
- **定義**: 重要な限定要素・制約条件
- **Phase1**: MUST
- **Phase2 recall**: SHOULD
- **Phase2 precision**: MUST or strong SHOULD

**例**: "レイテンシ要件", "コスト制約", "プライバシー保護"

### C要素（Use cases / deployment contexts）
- **定義**: 用途・適用シーン
- **Phase1**: SHOULD（MUSTにしない）
- **Phase2 recall**: SHOULD/OR only（**絶対にMUSTにしない**）
- **Phase2 precision**: SHOULD/OR only（**絶対にMUSTにしない**）

**例**: "ゲート", "入退室管理", "車載", "医療機器"

**重要**: C要素をMUSTにすると、**異なる用途での同一技術を見逃す**

### S要素（Semantic context for HyDE）
- **Phase1で抽出**: 代表公報のtitle/abstract/claimから技術的文脈を抽出
- **Phase2で使用**: semantic laneのHyDE summary生成に使用

---

## 典型的なPhase1→Phase2フロー

### Phase1: Representative Hunting

```yaml
# fulltext_precision lane only
query: "(顔認証 OR 顔識別) AND (プライバシー保護 OR 個人情報保護) AND (ゲート OR 入退室)"
filters:
  - field: "fi_full"  # edition symbol OK in Phase1
    op: "in"
    value: ["G06V10/82A", "G06V40/16B"]
field_boosts:
  title: 80
  abstract: 20
  claim: 40
  description: 40
```

**Phase1で抽出する語彙**:
```
A要素: ["顔特徴抽出", "照合処理", "個人識別"]
B要素: ["暗号化", "ローカル処理", "プライバシー保護"]
C要素: ["ゲート制御", "入退室管理", "アクセス制御"]
S要素: "カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する技術。プライバシー保護のため暗号化が求められる。"
```

### Phase2: Batch Retrieval

**recall lane**:
```yaml
query: "((顔特徴抽出 OR 顔認証 OR 顔識別) OR (バイオメトリクス)) AND (照合 OR 認証 OR matching)"
filters:
  - field: "fi_norm"  # edition symbol禁止
    op: "in"
    value: ["G06V10/82", "G06V40/16", "G06K9/00"]  # 複数コードでrecall確保
field_boosts:
  title: 40
  abstract: 10
  claim: 5
  description: 4
```

**precision lane**:
```yaml
query: "(顔特徴抽出 OR 顔認証) AND (暗号化 OR プライバシー保護) AND (ゲート OR 入退室)"
filters:
  - field: "fi_norm"  # edition symbol禁止
    op: "in"
    value: ["G06V10/82", "G06V40/16"]
field_boosts:
  title: 80
  abstract: 20
  claim: 40
  description: 40
```

**semantic lane (HyDE)**:
```yaml
text: |
  顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
  プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
  ゲートや入退室管理などの用途で使用される。
feature_scope: "wide"
```

**fusion**:
```yaml
runs:
  - {lane: "fulltext", run_id_lane: "recall-run-id"}
  - {lane: "fulltext", run_id_lane: "precision-run-id"}
  - {lane: "semantic", run_id_lane: "semantic-run-id"}
weights:
  fulltext: 1.0
  semantic: 0.8
rrf_k: 60
beta_fuse: 1.5
target_profile:
  fi_norm:
    "G06V10/82": 1.0
    "G06V40/16": 0.8
    "G06K9/00": 0.5
```

---

## v1.3からv1.4への移行ガイド

### SystemPrompt利用者（LLMエージェント）

1. **Phase1を必ず実行する**
   - 従来のinfield_lanesの前に、Phase1で20-50件の代表公報を取得
   - 代表公報からA/B/C/S要素を抽出

2. **Phase2クエリを代表語彙で再構築**
   - Phase0/Phase1のクエリを再利用しない
   - Phase1で抽出したA/B/C語彙で全レーンのクエリを再構築

3. **FI edition symbolの使い分け**
   - Phase1: `fi_full` 使用可
   - Phase2: `fi_norm` のみ（fi_full禁止）

4. **semantic lane でHyDE使用**
   - Phase2 semantic: 必ずHyDE summary生成
   - raw user text / keyword listは禁止

5. **run_multilane_searchを活用**
   - Phase2初回実行時、recall + precision + semanticを一括実行

### システム実装者

1. **fi_norm/fi_full両方の保存**
   - ストレージ層で両方のフィールドを保持
   - fi_norm: edition symbol除去版（例: `G06V10/82`）
   - fi_full: edition symbol付き版（例: `G06V10/82A`）

2. **融合層での2段階ブースト**
   - Primary boost: fi_norm
   - Secondary boost: fi_full（弱いヒント）

3. **get_publicationのid_type対応**
   - `pub_id`, `app_doc_id`, `app_id`, `exam_id` すべて対応
   - JP番号の正規化（特願/特開 → EPODOC）

---

## まとめ: v1.4の本質

v1.4の変更は、**実務サーチャーの黄金律「まず読む→用語確定→本番検索」を反映**したものです。

1. **Phase0**: 広く拾ってコード分布を把握
2. **Phase1**: 代表公報を精密に取得し、実際の語彙を確認
3. **Phase2**: Phase1の語彙で本番検索を再構築

この3段階により:
- **recall確保**: Phase2でedition symbol禁止＋広いFIコード
- **precision向上**: Phase1の実語彙使用＋A/B MUST, C SHOULD
- **semantic安定**: HyDEによりdrift（暴走）抑制

v1.3の数理的基礎（RRF, Fβ, コード認識ブースト）はすべてそのまま活用され、
パイプライン構造の改善で実務適用性を向上させています。
