# RRFusionのコンセプトと理論

## 1. RRFusionとは

RRFusion（Reciprocal Rank Fusion for Patent Search）は、特許先行技術調査に特化した多段階検索システムです。LLMエージェントがMCP（Model Context Protocol）経由で利用することを想定して設計されています。

### 設計思想

RRFusionは、プロのサーチャーが実務で行っている「まず読む→用語確定→本番検索」という黄金律を、システム化したものです。

**従来の一発検索の問題点:**
- ユーザの初期記述には曖昧な用語や用途語が含まれがち
- 実際の特許文献で使われる技術用語との乖離
- recall（網羅性）とprecision（精度）のバランスが取りにくい

**RRFusionのアプローチ:**
1. まず広く拾って技術分野を把握（Phase0）
2. 代表的な公報を精密に取得し、実際の語彙を確認（Phase1）
3. 確認した語彙で本番検索を再構築（Phase2）

## 2. なぜPhase0/1/2の3段階パイプラインなのか

### Phase0: Feature Extraction & Profiling

**目的:** 技術分野の理解とコード分布の把握

実務サーチャーがまず行う「この技術はどの分野に属するか」の判断をシステム化しています。

- ユーザの記述からA/A'/A''/B/C要素を抽出
- wide_searchで広く文献を取得（300-500件）
- FI/F-Termコード分布を分析（code_profiling）
- target_profileを構築

**アウトプット:**
- feature_set: 抽出した技術要素
- target_profile: FI/F-Termコードと重み
- tentative_codes: 暫定分類コードリスト

### Phase1: Representative Hunting

**目的:** 高品質な代表公報の取得と語彙抽出

実務サーチャーが「まず関連度の高い文献を数件読んで、どういう用語が使われているか確認する」プロセスをシステム化しています。

- fulltext_precisionで20-50件の代表公報を取得
- FI edition symbol（分冊記号）使用可（例: G06V10/82A）
- 代表公報からA/A'/A''/B/S要素を抽出
- synonym_clusterを更新（core → extended）

**アウトプット:**
- 代表公報リスト（20-50件）
- 更新されたsynonym_cluster
- HyDE summary用のS要素

### Phase2: Batch Retrieval

**目的:** 網羅的かつ精密な本番検索

Phase1で確認した語彙を使って、recall（網羅性）とprecision（精度）の両立を図ります。

- 4レーン構造: wide / recall / precision / semantic
- FI edition symbol禁止（fi_normのみ）
- semantic laneはHyDE必須
- run_multilane_searchで一括実行
- RRF融合で最終ランキング

**アウトプット:**
- 融合後の候補リスト
- 構造メトリクス（LAS/CCW/Fproxy等）
- レーン別貢献度

## 3. RRF（Reciprocal Rank Fusion）の基礎理論

### RRFとは

RRFは、複数の検索結果ランキングを融合する手法です。各文献の順位の逆数を合計してスコアを計算します。

**基本式:**

```
RRF_score(d) = Σ [ w_i / (k + rank_i(d)) ]
```

- `d`: 文献
- `rank_i(d)`: レーンiでの文献dの順位
- `w_i`: レーンiの重み
- `k`: 定数（デフォルト60）

### RRFusionの拡張

RRFusionでは、基本RRFに以下を追加しています：

**π(d) ブースト（文献固有スコア）:**

```
π(d) = w_code × π_code(d) + w_facet × π_facet(d) + w_lane × π_lane(d)
```

- `π_code(d)`: target_profileとのコード一致度
- `π_facet(d)`: A/B/C要素（facet_terms）の出現度
- `π_lane(d)`: 出現レーン数

**最終スコア:**

```
final_score(d) = RRF_score(d) × (1 + β × π(d))
```

- `β`: ブースト強度（デフォルト1.2）

### なぜRRFなのか

**利点:**
1. 異なる検索手法（fulltext/semantic）を統合可能
2. スコアスケールの違いを気にしなくてよい
3. 順位ベースなので外れ値に強い

**課題:**
- 単純RRFでは日本特許の分類コード情報を活用できない
- → target_profileとπ(d)ブーストで対応

## 4. 用語定義

### 技術要素の分類

RRFusionでは、発明の構成要素を以下のように分類します。

#### A要素（Core technical mechanisms）

**定義:** 本質的な構成要素・コア技術

**例:**
- 顔認証アルゴリズム
- 冷却構造
- センサ構成
- 特徴抽出手段

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD（広いOR-group）
- Phase2 precision: MUST

#### A'要素（Target/condition）

**定義:** 発明が対象とする特徴的な状況・条件

**例:**
- 部分遮蔽
- マスク着用
- 欠損領域
- ノイズ環境

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD
- Phase2 precision: MUST

#### A''要素（Technical means）

**定義:** 技術的手段・アプローチ

**例:**
- 重み付け（enhancement）
- 補完（compensation）
- 選択的抽出（selection）
- 正規化（normalization）

**クエリでの扱い:**
- Phase1: MUST or strong SHOULD
- Phase2 recall: SHOULD（全approach_categoriesをOR-groupで）
- Phase2 precision: MUST or strong SHOULD

**重要:** A''要素は複数のapproach_categoriesにまたがることが多いため、OR-groupで幅広くカバーします。

#### B要素（Constraints）

**定義:** 重要な限定要素・制約条件

**例:**
- レイテンシ要件
- 暗号化処理
- リアルタイム性
- 認証精度

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD
- Phase2 precision: MUST or strong SHOULD

#### C要素（Use cases / deployment contexts）

**定義:** 用途・適用シーン

**例:**
- ゲート
- 入退室管理
- 車載
- 医療機器

**クエリでの扱い:**
- Phase1: SHOULD（**絶対にMUSTにしない**）
- Phase2 recall: SHOULD/OR only
- Phase2 precision: SHOULD/OR only

**重要な原則: C要素は絶対にMUSTにしない**

同一の技術が異なる用途で使われる先行技術を見逃すことになります。

悪い例:
```
(顔認証) AND (ゲート) AND (入退室管理)
```
→ 車載用途の顔認証を見逃す

良い例:
```
(顔認証) AND (プライバシー保護) AND (ゲート OR 入退室 OR 車載 OR 医療)
```
→ C要素はOR-groupに

#### S要素（Semantic context for HyDE）

**定義:** Phase1の代表公報から抽出した技術的文脈

**Phase2 semanticで使用:**
- HyDE summary生成のベース
- 1-3段落の自然言語パラグラフ
- 用途語（C要素）は最小限に

### レーン（Lane）

検索クエリの種類を「レーン」と呼びます。

**Phase0:**
- fulltext_wide: 広いOR-groups、コード分布把握用

**Phase2:**
- fulltext_recall: 網羅性重視のfulltext検索
- fulltext_precision: 精度重視のfulltext検索
- semantic: セマンティック類似検索（HyDE使用）

**Phase1では:**
- fulltext_precision のみ使用

### Recall vs Precision

**Recall（再現率・網羅性）:**
- 関連文献のうち、どれだけ拾えたか
- 高いrecall = 漏れが少ない

**Precision（適合率・精度）:**
- 取得した文献のうち、どれだけ関連があるか
- 高いprecision = ノイズが少ない

**RRFusionのアプローチ:**
- recall laneで広く拾う
- precision laneで絞る
- RRF融合でバランスを取る

### HyDE（Hypothetical Document Embeddings）

**定義:** 仮想的な文献を生成し、そのembeddingで検索する手法

**RRFusionでの使い方:**
- Phase1の代表公報から技術的文脈を抽出
- 1-3段落の自然言語サマリーを生成
- raw user textやkeyword listは禁止

**なぜHyDEが必要か:**
- raw user textには用途語や曖昧語が含まれがち
- semantic searchは概念的な類似性で引きずられやすい（drift）
- 代表公報ベースのHyDEで技術的本質に焦点を当てる

## 5. 従来の検索手法との違い

### 従来の一段階検索

```
ユーザ記述 → クエリ設計 → 検索実行 → 結果
```

**問題点:**
- ユーザ記述の語彙が実際の特許文献と乖離
- 用途語をMUSTにしがち → recall低下
- semantic searchがdrift（暴走）しやすい

### RRFusionの三段階検索

```
Phase0: ユーザ記述 → wide_search → コード分布把握
    ↓
Phase1: precision query → 代表公報取得 → 語彙抽出
    ↓
Phase2: 確定語彙 → 4レーン検索 → RRF融合 → 結果
```

**利点:**
- 実際の特許文献で使われる語彙を確認してから本番検索
- recall/precisionのバランスをレーン設計で調整
- semantic drift（暴走）をHyDEで抑制

## 6. システム構成における位置づけ

RRFusionは、以下の3層構造の中間層です：

```
┌─────────────────────┐
│  LLMエージェント      │ ← Claude等、MCP経由で利用
├─────────────────────┤
│  RRFusion MCP       │ ← このシステム
│  - SystemPrompt     │
│  - Fusion Engine    │
│  - MCPツール群       │
├─────────────────────┤
│  バックエンド         │
│  - 特許DB           │
│  - Fulltext検索     │
│  - Semantic検索     │
└─────────────────────┘
```

**RRFusionの役割:**
- LLMエージェントに検索戦略を指示（SystemPrompt）
- 複数検索結果の融合（RRF + π(d)ブースト）
- 構造メトリクスによる品質評価

## 7. MVP（Proof of Concept）としての位置づけ

現在のRRFusionは、実務検証のためのMVPです。

**想定される使い方:**
- プロのサーチャーがLLMエージェント経由で利用
- 検索結果を人間が最終レビュー
- SystemPrompt YAMLを継続的に改善

**今後の発展可能性:**
- 代表公報の自動選定精度向上
- 語彙抽出プロセスの最適化
- non-JP（US/EP）パイプラインの拡充
- バックエンド検索エンジンの改善

## まとめ

RRFusionは、プロのサーチャーの実務プロセス「まず読む→用語確定→本番検索」をシステム化した、三段階パイプライン型の特許検索システムです。

**核心:**
- Phase0で技術分野を把握
- Phase1で実語彙を確認
- Phase2で確定語彙による本番検索

次章では、各Phaseの詳細な動作を学びます。
