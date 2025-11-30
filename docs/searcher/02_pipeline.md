# パイプライン詳細

本章では、RRFusionの三段階パイプライン（Phase0/1/2）の詳細な動作を説明します。

## パイプライン全体像

```
Phase0: Feature Extraction & Profiling
  ├─ feature_extraction (LLM推論)
  ├─ wide_search (rrf_search_fulltext_raw)
  ├─ code_profiling (get_provenance)
  └─ ユーザ確認: invention_interpretation

Phase1: Representative Hunting
  ├─ representative_hunting (rrf_search_fulltext_raw)
  ├─ date調整（動的）
  ├─ vocabulary_feedback
  │   ├─ peek_snippets (primary: 20-30件)
  │   ├─ 語彙抽出 (LLM推論)
  │   └─ [必要に応じて] extended extraction (10件)
  └─ ユーザ確認: representative_review_confirmation

Phase2: Batch Retrieval
  ├─ run_multilane_search
  │   ├─ fulltext_recall
  │   ├─ fulltext_precision
  │   └─ semantic (HyDE)
  ├─ rrf_blend_frontier
  ├─ get_provenance (必須)
  ├─ peek_snippets
  └─ [必要に応じて] rrf_mutate_run (cheap_path)
```

## Phase0: Feature Extraction & Profiling

### 目的

技術分野の理解とコード分布の把握。「この発明はどの分野に属するか」を判断します。

### ステップ1: feature_extraction

**入力:**
- ユーザの発明記述（自然言語）

**処理:**
- LLMが以下を抽出
  - A要素: コア技術
  - A'要素: 対象・条件
  - A''要素: 技術的手段
  - B要素: 制約条件
  - C要素: 用途
- 2-3つの解釈（narrow/medium/broad）を生成
- synonym_clusterを構築（coreのみ）
- tentative_codes（暫定FI/F-Termコード）を推定

**アウトプット:**
```yaml
feature_set:
  A_terms: ["顔認証", "顔識別", "face recognition"]
  A_prime_terms: ["部分遮蔽", "マスク", "オクルージョン"]
  A_double_prime_terms: ["重み付け", "強化", "補完"]
  B_terms: ["プライバシー保護", "暗号化"]
  C_terms: ["ゲート", "入退室管理", "アクセス制御"]
  synonym_clusters:
    core:
      face_recognition: ["顔認証", "顔識別", "face recognition"]
      occlusion: ["遮蔽", "マスク", "オクルージョン"]
  tentative_codes:
    fi: ["G06V10/82", "G06V40/16"]
    ft: ["5B089AA01", "5B089CA13"]
```

**ユーザ確認ポイント:**

この段階で`user_confirmation_protocol.invention_interpretation`を使用し、発明の解釈範囲を確認します。

```
【発明の理解】
以下のように理解しました。

- コア技術（A）: 顔認証・個人識別
- 対象・条件（A'）: マスク等による部分遮蔽
- 技術的手段（A''）: 特徴量の重み付け・強化・補完
- 用途（C）: ゲート・入退室管理

【確認】
この理解で検索を進めてよろしいですか？

A: この理解で進める
B: コア技術の範囲を広げたい
C: コア技術の範囲を狭めたい
D: 用途（C）も必須条件として扱いたい
```

### ステップ2: technical_approach_confirmation（オプション）

A''要素（技術的手段）が複数のapproach_categoriesに該当する場合、ユーザに重視するアプローチを確認します。

**approach_categories:**
- enhancement: 強化・増幅系（重み付け、強調、ブースト）
- selection: 選択・抽出系（選択的使用、有効領域抽出）
- compensation: 補完・推定系（補完、復元、推定）
- switching: 切替・代替系（フォールバック、置換）
- normalization: 正規化・補正系（正規化、調整、スケーリング）

**ユーザ確認:**

```
【技術アプローチの確認】
この発明の技術的手段として、複数のアプローチが考えられます。

A: 強化・重み付け（特徴量の重みを増加させる）
B: 選択的使用（有効な領域のみを選択して使用）
C: 補完・推定（欠損部分を推定・復元する）
D: すべてを均等にカバー（推奨）
```

**結果:**
- D選択時: すべてのカテゴリをOR-groupに含める
- A/B/C選択時: 選択されたカテゴリを優先（MUSTに近い扱い）

**重要:** レーンは増やさない。単一クエリ内のOR構造とMUST/SHOULDの重み付けで対応。

### ステップ3: wide_search

**目的:** 広く文献を拾ってコード分布を把握

**ツール:** `rrf_search_fulltext_raw`

**クエリ設計:**
- 広いOR-groups
- 全approach_categoriesをOR-groupに含める
- No NEAR
- No tight constraints
- C要素はMUSTにしない

**例:**
```yaml
query: "((顔認証 OR 顔識別 OR face recognition) OR (バイオメトリクス OR 生体認証)) AND (遮蔽 OR マスク OR オクルージョン) AND (強化 OR 重み付け OR 選択 OR 補完 OR 正規化)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
  - {lop: "and", field: "country", op: "in", value: ["JP"]}
field_boosts: {title: 80, abst: 10, claim: 5, desc: 1}
top_k: 800
```

**目標ヒット数:**
- 300-500件（top_k=800時）
- < 100件の場合: over-constraining（制約過多）→ 緩和

### ステップ4: code_profiling

**ツール:** `get_provenance`

**入力:** wide_searchのrun_id

**処理:**
- FI/F-Termコードの分布を分析
- top 10-20コードを抽出
- 重みを算出

**アウトプット:**
```yaml
target_profile:
  fi:
    "G06V10/82": 1.0
    "G06V40/16": 0.9
    "G06V40/172": 0.6
    "G06K9/00": 0.5
  ft:
    "5B089AA01": 0.8
    "5B089CA13": 0.6
```

**注意:**
- fi_normのみ使用（edition symbolなし）
- 用途コードに過度に引きずられないよう注意

## Phase1: Representative Hunting

### 目的

高品質な代表公報を20-50件取得し、実際の特許文献で使われる語彙を抽出します。

### ステップ1: date調整ポリシー

Phase1実行前に、検索対象年代を設定します。

**初期設定:**
- デフォルト: 10年前以降
- 根拠: 基礎技術を含めて広くカバー

**動的調整ルール:**

| ヒット数 | アクション |
|---------|-----------|
| > 300件 | 5-7年前以降に絞る |
| > 500件 | 5年前以降に絞る |
| < 30件  | 15年前以降に緩和 |
| < 10件  | date制限除去 + クエリ緩和 |

**ユーザ確認:**

```
【検索対象年代の確認】
先行技術調査の対象年代を確認させてください。

A: 過去10年（2015年以降）- 標準
B: 過去5年（2020年以降）- 最新技術に集中
C: 過去15年（2010年以降）- 基礎技術も含める
D: 年代制限なし - 最も広くカバー
```

### ステップ2: representative_hunting

**ツール:** `rrf_search_fulltext_raw`

**レーン:** fulltext_precision のみ

**クエリ設計:**
- A要素: MUST
- A'要素: MUST
- A''要素: MUST or strong SHOULD
- B要素: SHOULD
- C要素: SHOULD（OR-groupのみ）
- NEAR使用可（A-A'またはA'-A''の近接性）

**FI使用:**
- **fi_full使用可**（edition symbol付き）
- 例: `G06V10/82A`, `G06V40/16B`
- 目的: 高精度で代表公報を絞り込む

**field_boosts:**
```yaml
{title: 80, abst: 20, claim: 40, desc: 40}
```

**例:**
```yaml
query: "(顔認証 OR face recognition) AND (遮蔽 OR マスク) AND (特徴量 AND (重み付け OR 強化))"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V40/16B"]}
  - {lop: "and", field: "date", op: ">=", value: "2015-01-01"}
field_boosts: {title: 80, abst: 20, claim: 40, desc: 40}
top_k: 100
```

**目標取得数:**

| 技術分野の広さ | 代表公報数 | 条件 |
|--------------|-----------|-----|
| 狭い分野 | 20-30件 | Phase0のFI分布が3コード以内 |
| 中程度 | 30-50件 | Phase0のFI分布が4-9コード |
| 広い分野 | 40-50件 | Phase0のFI分布が10コード以上 |

### ステップ3: vocabulary_feedback

Phase1で取得した代表公報から、Phase2クエリに使う語彙を抽出します。

#### 3-1. extraction_depth（抽出深度）の決定

**primary（標準抽出）:**
- fields: ["title", "abst", "claim"]
- count: 20-30件
- 目的: A/A'/B要素の基本語彙
- コスト: 低

**extended（拡張抽出）:**
- fields: ["title", "abst", "claim", "desc"]
- desc_limit: 冒頭1000文字 または【発明を実施するための形態】
- count: 10件
- 目的: A''要素の補完、実装バリエーション
- コスト: 中〜高

**自動トリガー条件（extended）:**
- primary抽出でA''要素（技術的手段）が3個未満
- approach_categoriesが1カテゴリのみに偏っている
- ユーザが明示的に拡張抽出を要求

#### 3-2. primary extraction

**ツール:** `peek_snippets`

```yaml
parameters:
  count: 20-30
  fields: ["title", "abst", "claim"]
```

**LLM推論による語彙抽出:**

抽出対象:
- A_terms: コア技術用語（動作・構造・機能）
- A_prime_terms: 対象・条件用語
- B_terms: 制約・効果用語
- S_context: semantic用の技術的文脈（**用途語を含めず**）

**アウトプット例:**
```yaml
extracted_vocabulary:
  A_terms: ["顔特徴抽出", "照合処理", "個人識別", "顔画像解析"]
  A_prime_terms: ["部分遮蔽", "顔領域欠損", "マスク装着", "オクルージョン状態"]
  B_terms: ["認証精度", "暗号化処理", "ローカル処理", "プライバシー保護"]
  S_context: "カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。部分遮蔽時には非遮蔽領域の特徴を活用する。"
```

**品質チェック:**
- A_termsが3個以上抽出されているか
- A''_termsが3個以上抽出されているか → 未満ならextended抽出へ

#### 3-3. extended extraction（条件付き）

**トリガー:**
- A''_terms < 3個
- approach_categoriesが1つに偏っている

**ツール:** `peek_snippets`（desc付き）

```yaml
parameters:
  count: 10
  fields: ["title", "abst", "claim", "desc"]
  per_field_chars: {desc: 1000}
```

**抽出対象:**
- A''_terms（技術的手段）
- approach_categoriesを参照し、カテゴリ別に抽出

**読むべきセクション:**
- 【発明を実施するための形態】冒頭
- 【課題を解決するための手段】
- 【発明の効果】

**アウトプット例:**
```yaml
extended_A_double_prime_terms:
  enhancement: ["重み増加", "強調処理", "ブースト", "加重平均"]
  selection: ["選択的抽出", "有効領域抽出", "可視部分のみ使用"]
  compensation: ["補完処理", "推定復元", "欠損補填", "特徴再構成"]
```

#### 3-4. synonym_clusterの更新

**core → extendedへの追加:**

```yaml
synonym_clusters:
  core:  # Phase0で構築
    face_recognition: ["顔認証", "顔識別", "face recognition"]
  extended:  # Phase1で追加
    face_recognition: ["顔特徴抽出", "顔画像解析", "個人識別", "照合処理"]
    occlusion: ["部分遮蔽", "顔領域欠損", "マスク装着", "オクルージョン状態"]
```

**ルール:**
- 既存のcoreと重複する用語は追加しない
- 抽出元の公報番号を記録
- approach_categoriesのカテゴリを付与
- extended抽出で追加した用語には[ext]マークを付与

#### 3-5. Phase2クエリの再構築

**fulltext_recall:**
- 更新されたsynonym_cluster全体を使用
- A/A'/A''/B: SHOULD（広いOR-group）
- C: SHOULD（OR-groupのみ）
- 全approach_categoriesをOR-groupに含める

**fulltext_precision:**
- core + 高頻度extended用語を使用
- A + A': MUST
- A'': MUST or strong SHOULD（優先approach）
- B: SHOULD
- C: SHOULD（OR-groupのみ）
- NEAR使用可

**semantic (HyDE):**
- S_context + A_terms + A_prime summaryから生成
- 1-3段落の自然言語
- **用途語（C_terms）は最小限に**

### ステップ4: representative_review_confirmation

**ユーザ確認:**

```
【代表公報レビュー結果】
上位30件のスニペットを確認しました。

- 技術的に近い文献: 18件
- 部分的に関連: 8件
- 関連薄い: 4件

【確認】
Phase2（本検索）の方向性を選択してください。

A: このまま進める（現在のクエリ設計で本検索）
B: もう少し広げたい（recall重視に調整）
C: もう少し絞りたい（precision重視に調整）
D: 別の観点を追加したい
```

## Phase2: Batch Retrieval

### 目的

Phase1で確定した語彙を使って、網羅的かつ精密な本番検索を実行します。

### ステップ1: run_multilane_search

**ツール:** `run_multilane_search`

**3レーン構成:**
1. fulltext_recall
2. fulltext_precision
3. semantic

**重要な制約:**
- **FI edition symbol禁止**（fi_normのみ）
- 例: `G06V10/82`（OK）、`G06V10/82A`（NG）
- 理由: edition symbolは割り当てが不安定で、recall低下の原因

#### レーン1: fulltext_recall

**目的:** 広い網羅性

**クエリ設計:**
```yaml
query: "((顔特徴抽出 OR 顔認証 OR 顔識別 OR 個人識別) OR (バイオメトリクス OR 生体認証)) AND (部分遮蔽 OR マスク OR 顔領域欠損 OR オクルージョン) AND (重み付け OR 強化 OR 選択 OR 補完 OR 正規化 OR 推定)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
field_boosts: {title: 40, abst: 10, claim: 5, desc: 4}
top_k: 400
```

**特徴:**
- すべてのsynonym_cluster（core + extended）を使用
- 全approach_categoriesをOR-groupに
- NEAR使用しない（recall優先）
- 複数FIコードでrecall確保

#### レーン2: fulltext_precision

**目的:** 高精度候補の取得

**クエリ設計:**
```yaml
query: "(顔特徴抽出 OR 顔認証) AND (部分遮蔽 OR マスク) AND (特徴量 AND (重み付け OR 強化)) AND (認証精度 OR プライバシー保護) AND (ゲート OR 入退室 OR アクセス制御)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
field_boosts: {title: 80, abst: 20, claim: 40, desc: 40}
top_k: 200
```

**特徴:**
- A + A': MUST
- A'': MUST or strong SHOULD（優先approach）
- B: SHOULD
- C: SHOULD（OR-groupのみ）
- NEAR使用可（例: `*N30"(遮蔽 OR マスク) (特徴量 OR 特徴)"`）
- negative_hints適用可（簡易なNOT条件）

#### レーン3: semantic (HyDE)

**目的:** 概念的類似性のカバー

**HyDE summary生成:**
```yaml
text: |
  顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
  マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けまたは補完することで認証精度を維持する。
  プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
feature_scope: "wide"
top_k: 300
```

**重要:**
- Phase1のS_contextから生成
- **raw user text禁止**
- **keyword list禁止**
- 1-3段落の自然言語パラグラフ
- 用途語（C_terms）は最小限に

### ステップ2: rrf_blend_frontier

**ツール:** `rrf_blend_frontier`

**パラメータ:**
```yaml
runs:
  - {lane: "fulltext", run_id_lane: "recall-run-id"}
  - {lane: "fulltext", run_id_lane: "precision-run-id"}
  - {lane: "semantic", run_id_lane: "semantic-run-id"}
weights:
  fulltext: 1.0
  semantic: 0.8
lane_weights:
  recall: 1.0
  precision: 1.0
  semantic: 0.8
target_profile:
  fi:
    "G06V10/82": 1.0
    "G06V40/16": 0.9
rrf_k: 60
beta_fuse: 1.2
```

### ステップ3: get_provenance（必須）

**ツール:** `get_provenance`

**入力:** fusion run_id

**アウトプット:**
- code_freqs: FI/F-Termコード頻度分布
- lane_contributions: 各レーンの貢献度
- structural_metrics: LAS/CCW/S_shape/F_struct/Fproxy

**構造メトリクス:**

| メトリクス | 説明 | 健全範囲 | 警告値 |
|-----------|------|---------|--------|
| LAS | Lane Agreement Score（レーン間一致度） | >= 0.4 | < 0.3 |
| CCW | Class Consistency Weight（分類一貫性） | >= 0.5 | < 0.3 |
| S_shape | Score-Shape Index（スコア形状） | 0.15-0.35 | > 0.5 |
| Fproxy | Fusion Proxy Score（総合評価） | >= 0.5 | < 0.5 |

### ステップ4: peek_snippets

**ツール:** `peek_snippets`

```yaml
parameters:
  limit: 30
  budget_bytes: 4096
```

**目的:** 上位候補のクイックチェック

### ステップ5: fusion_result_confirmation

**ユーザ確認:**

```
【検索結果サマリー】
融合後の上位候補: 342件

- 技術分野分布: G06V10/82 (45%), G06V40/16 (32%), G06K9/00 (18%)
- 各レーンからの貢献: recall 38%, precision 42%, semantic 20%

【確認】

A: 結果を確認する（上位30件のスニペット表示）
B: recallを上げたい（fulltext_recallの重みを増加）
C: precisionを上げたい（fulltext_precisionの重みを増加）
D: 検索をやり直したい（Phase1から再実行）
```

### ステップ6: rrf_mutate_run（cheap_path）

結果が不十分な場合、パラメータ調整で改善を試みます。

**ツール:** `rrf_mutate_run`

**調整可能パラメータ:**
- weights: {fulltext, semantic, code}
- lane_weights: {recall, precision, semantic}
- pi_weights: {code, facet, lane}
- rrf_k
- beta_fuse

**cheap_path戦略:**
- 新レーン追加の前に、パラメータ調整で改善を試みる
- 最大2回のmutate試行
- それでも改善しない場合のみ、新レーン追加を検討

**診断パターン別の対処:**

| 症状 | 原因 | 対処 |
|------|------|------|
| 明らかな先行技術を見逃す | recall不足 | lane_weights.recall を増加 |
| 無関連文献が多い | precision不足 | lane_weights.precision を増加 |
| S_shape > 0.5 | semantic優勢 | weights.semantic を減少 |
| CCW < 0.3 | 分類散乱 | pi_weights.code を増加 |

## ユーザ確認プロトコル（user_confirmation_protocol）

v1.5では、すべてのユーザ確認を統一フォーマットで実施します。

**確認ポイント一覧:**
1. invention_interpretation（Phase0後）
2. technical_approach_confirmation（Phase0、オプション）
3. date_range_confirmation（Phase1前）
4. representative_review_confirmation（Phase1後）
5. fusion_result_confirmation（Phase2後）

**フォーマット:**
```
【現状の説明】
...

【確認】
...

A: 選択肢1
B: 選択肢2
C: 選択肢3
D: 選択肢4

上記以外の修正があれば、自然文でお伝えください。
```

## まとめ

Phase0/1/2パイプラインの流れ:

1. **Phase0**: feature_extraction → wide_search → code_profiling
2. **Phase1**: representative_hunting → vocabulary_feedback
3. **Phase2**: run_multilane_search → rrf_blend_frontier → get_provenance

各Phaseでユーザ確認を取りながら、段階的に検索精度を高めていきます。

次章では、クエリ設計の詳細を学びます。
