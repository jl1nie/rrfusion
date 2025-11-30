# 検索結果のチューニング方法

本章では、検索結果の品質を評価し、改善する方法を解説します。

## 1. 構造メトリクス（Structural Metrics）

RRFusionは、融合結果の品質を評価するための構造メトリクスを提供します。

### 評価対象

**top-50文献:**
- すべてのメトリクスはtop-50文献に基づいて計算
- evaluation_k = 50

**診断シグナルとして使用:**
- Hard filterではない
- 値が低い場合の「警告」として機能

### LAS（Lane Agreement Score）

**定義:** レーン間の一致度

**計算方法:**
- 各レーンペアのtop-50 Jaccard係数の平均

```
LAS = average(Jaccard(lane_i, lane_j)) for all pairs
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

**健全範囲:**
- LAS >= 0.4: 健全
- 0.3 <= LAS < 0.4: 注意
- LAS < 0.3: 警告

**意味:**
- 高いLAS: レーン間で一致する文献が多い → 安定した融合
- 低いLAS: レーン間で一致する文献が少ない → レーン設計の見直しが必要

**低LAS時の対処:**
- semantic weightを減少
- fulltext_precisionが狭すぎないか確認
- クエリ設計を見直し（A/A'要素の一貫性）

### CCW（Class Consistency Weight）

**定義:** 分類の一貫性

**計算方法:**
- top-50のFIコード分布のエントロピーから算出

```
CCW = 1 - normalized_entropy(FI_distribution)
```

**健全範囲:**
- CCW >= 0.5: 健全
- 0.3 <= CCW < 0.5: 注意
- CCW < 0.3: 警告

**意味:**
- 高いCCW: 特定の技術分野に集中 → 精度が高い
- 低いCCW: 分類が散乱 → ノイズが多い

**低CCW時の対処:**
- FI/F-Termフィルタを強化
- target_profileの重みを調整（pi_weights.code増加）
- クエリを絞る（precision lane）

### S_shape（Score-Shape Index）

**定義:** スコア分布の形状

**計算方法:**
- 上位3件のスコア合計 / 上位50件のスコア合計

```
S_shape = sum(scores[0:3]) / sum(scores[0:50])
```

**健全範囲:**
- 0.15 <= S_shape <= 0.35: 健全
- 0.35 < S_shape < 0.5: 注意
- S_shape > 0.5: 警告（スコア集中）

**意味:**
- 健全なS_shape: スコアが適度に分散 → バランスの良いランキング
- 高いS_shape: 上位数件にスコアが集中 → semantic dominance（暴走）の可能性

**高S_shape時の対処:**
- semantic weightを減少
- beta_fuseを減少
- HyDE summaryを見直し（用途語が多すぎないか）

### F_struct（Structural F-score）

**定義:** LASとCCWの組み合わせ

**計算方法:**
- LASとCCWのF1スコア風組み合わせ

```
F_struct = 2 × LAS × CCW / (LAS + CCW)
```

**健全範囲:**
- F_struct >= 0.4: 健全
- 0.3 <= F_struct < 0.4: 注意
- F_struct < 0.3: 警告

### Fproxy（Fusion Proxy Score）

**定義:** 総合評価スコア

**計算方法:**
- F_structにS_shapeペナルティを適用

```
Fproxy = F_struct × (1 - penalty(S_shape))
penalty(S_shape) = max(0, (S_shape - 0.35) / 0.65)
```

**判定基準:**
- Fproxy >= 0.5: 健全 → 結果確認へ
- Fproxy < 0.5: チューニング推奨 → rrf_mutate_run
- Fproxy < 0.4（2回mutate後）: レーン設計見直し

## 2. cheap_path_first戦略

### 基本方針

新レーン追加の前に、パラメータ調整で改善を試みます。

**理由:**
- 新レーン追加はコストが高い（新たな検索実行）
- パラメータ調整は低コスト（既存結果の再融合）
- 多くの場合、パラメータ調整で十分に改善可能

### cheap_pathの手順

```
Step1: rrf_blend_frontier（初回融合）
  ↓
Step2: get_provenance（必須）
  ↓
Step3: peek_snippets（上位候補確認）
  ↓
Step4: 診断 → 必要に応じてrrf_mutate_run
  ↓
Step5: get_provenance + peek_snippets
  ↓
Step6: まだ不十分 → 再度rrf_mutate_run（最大2回）
  ↓
Step7: 改善しない → 新レーン追加を検討
```

### exit_criteria（終了基準）

**成功:**
- Fproxy >= 0.5
- Top 20 snippetsに A-level候補が5件以上
- LAS >= 0.3 AND CCW >= 0.4

**失敗:**
- Fproxy < 0.4（2回mutate後）
- Top 20 snippetsに A-level候補が0件

**失敗時の対処:**
- 既存レーンの制約を緩和
- 新レーン追加は最終手段（本当に必要な場合のみ）

## 3. rrf_mutate_runの活用

### 概要

**ツール:** `rrf_mutate_run`

**目的:** レーンを再実行せず、融合パラメータのみ調整

**利点:**
- 低コスト（検索再実行不要）
- 高速（融合計算のみ）
- 繰り返し試行可能

### 調整可能パラメータ

**weights:**
- fulltext: fulltextレーンの基本重み
- semantic: semanticレーンの基本重み
- code: codeブースト（target_profile）の重み

**lane_weights:**
- recall: fulltext_recallの重み
- precision: fulltext_precisionの重み
- semantic: semanticレーンの重み

**pi_weights:**
- code: π_code(d)の重み（target_profile一致度）
- facet: π_facet(d)の重み（A/B/C要素出現度）
- lane: π_lane(d)の重み（出現レーン数）

**rrf_k:**
- RRF計算の定数（デフォルト60）

**beta_fuse:**
- π(d)ブースト強度（デフォルト1.2）

### 推奨範囲

| パラメータ | デフォルト | 推奨範囲 |
|-----------|-----------|---------|
| weights.fulltext | 1.0 | 0.5-1.5 |
| weights.semantic | 0.8 | 0.5-1.2 |
| weights.code | 0.3 | 0.0-0.5 |
| lane_weights.recall | 1.0 | 0.5-1.5 |
| lane_weights.precision | 1.0 | 0.5-1.5 |
| lane_weights.semantic | 0.8 | 0.3-1.0 |
| pi_weights.code | 0.4 | 0.2-0.6 |
| pi_weights.facet | 0.3 | 0.2-0.6 |
| pi_weights.lane | 0.3 | 0.1-0.4 |
| rrf_k | 60 | 40-120 |
| beta_fuse | 1.2 | 0.8-2.0 |

### MutateDeltaの注意点

**ABSOLUTE OVERWRITE（絶対値上書き）:**
- MutateDeltaの値は、現在値からの増分ではなく、**絶対値**

**例:**
```yaml
# 現在の設定
weights:
  fulltext: 1.0
  semantic: 0.8

# MutateDelta
mutate_delta:
  weights:
    semantic: 0.5  # ← 0.8 - 0.3 ではなく、0.5に設定

# 結果
weights:
  fulltext: 1.0
  semantic: 0.5  # ← 絶対値0.5
```

## 4. 診断パターンと対処法

### パターン1: low_recall（網羅性不足）

**症状:**
- 明らかな先行技術を見逃している
- CCWは高いが、関連文献が少ない
- ユーザが「この文献が入ってないのはおかしい」と指摘

**原因:**
- FIフィルタが狭すぎる
- クエリにsynonymが不足
- approach_categoriesの一部が欠けている
- precision laneが強すぎる

**対処:**

1. **FIコードを拡大:**
```yaml
# Before
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}

# After
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
```

2. **synonymを追加:**
- vocabulary_feedbackをやり直し
- Phase1の代表公報を増やす

3. **approach_categoriesを確認:**
```yaml
# Before
A_double_prime: "(重み付け OR 強化)"

# After
A_double_prime: "(重み付け OR 強化 OR 選択 OR 抽出 OR 補完 OR 推定)"
```

4. **lane_weightsを調整:**
```yaml
# rrf_mutate_run
mutate_delta:
  lane_weights:
    recall: 1.5      # recall重視
    precision: 0.7   # precision抑制
```

### パターン2: low_precision（精度不足）

**症状:**
- 無関連文献が上位に多い
- CCWが低い（散乱している）
- peek_snippetsで「これは違う」という文献が多い

**原因:**
- クエリが広すぎる
- semantic drift（暴走）
- negative_hints不足

**対処:**

1. **A/A'をMUSTに:**
```yaml
# Before
query: "(顔認証 OR 画像認識) AND (遮蔽 OR ノイズ)"

# After
query: "(顔認証 OR 顔識別) AND (遮蔽 OR マスク) AND (特徴量 AND (重み付け OR 強化))"
```

2. **NEARで近接性を担保:**
```yaml
# precision lane
query: '(顔認証) AND *N30"(遮蔽 OR マスク) (特徴量 OR 特徴)"'
```

3. **negative_hintsを適用:**
```yaml
query: "(顔認証) AND (遮蔽 OR マスク) NOT (指紋 NOT 顔)"
```

4. **semantic weightを減少:**
```yaml
# rrf_mutate_run
mutate_delta:
  weights:
    semantic: 0.5   # semantic抑制
  lane_weights:
    precision: 1.3  # precision重視
```

### パターン3: semantic_dominance（semantic暴走）

**症状:**
- S_shape > 0.5
- 上位結果がsemantic laneからのみ
- fulltext laneが underrepresented

**原因:**
- semantic weightが高すぎる
- HyDE textが一般的すぎる
- beta_fuseが高すぎる

**対処:**

1. **semantic weightを減少:**
```yaml
# rrf_mutate_run
mutate_delta:
  weights:
    semantic: 0.4
  lane_weights:
    semantic: 0.5
```

2. **HyDE summaryを見直し:**
```yaml
# Before - 一般的すぎる
text: "画像認識技術でゲートを制御する。"

# After - 技術的に具体的
text: "顔認証技術において、マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けすることで認証精度を維持する。"
```

3. **beta_fuseを減少:**
```yaml
# rrf_mutate_run
mutate_delta:
  beta_fuse: 0.9
```

4. **fulltext weightsを増加:**
```yaml
# rrf_mutate_run
mutate_delta:
  weights:
    fulltext: 1.3
    semantic: 0.4
```

### パターン4: approach_imbalance（アプローチ偏り）

**症状:**
- 結果が単一の技術アプローチのみ
- 例: enhancement系のみで、selection/compensation系が無い

**原因:**
- A''要素が単一アプローチに偏っている
- approach_categoriesの一部が欠けている

**対処:**

1. **approach_categoriesカバレッジを確認:**
```yaml
# Before
A_double_prime: "(重み付け OR 強化)"

# After
A_double_prime: "(重み付け OR 強化 OR 選択 OR 抽出 OR 補完 OR 推定 OR 切替 OR 正規化)"
```

2. **ユーザ確認を取る:**
- technical_approach_confirmationを実施
- 特定のアプローチに絞るべきか確認

3. **vocabulary_feedbackをやり直し:**
- extended extractionを実行
- 実施形態から多様なアプローチを抽出

## 5. review_loop（レビューループ）

### ユーザ確認プロトコル

**fusion_result_confirmation:**

```
【検索結果サマリー】
融合後の上位候補: 342件

- 技術分野分布: G06V10/82 (45%), G06V40/16 (32%), G06K9/00 (18%)
- 各レーンからの貢献: recall 38%, precision 42%, semantic 20%
- 構造メトリクス: Fproxy 0.52, LAS 0.38, CCW 0.61, S_shape 0.28

【確認】

A: 結果を確認する（上位30件のスニペット表示）
B: recallを上げたい（fulltext_recallの重みを増加）
C: precisionを上げたい（fulltext_precisionの重みを増加）
D: 検索をやり直したい（Phase1から再実行）

パラメータの具体的な調整があれば、自然文でお伝えください。
```

### max_cycles

**推奨:** 2 mutate cycles before asking user

**理由:**
- 1回目のmutateで大きく改善することが多い
- 2回目で微調整
- 3回目以降は効果が薄い → ユーザ確認

## 6. 実践例

### 例1: CCW低い（分類散乱）

**初回融合結果:**
```yaml
metrics:
  Fproxy: 0.42
  LAS: 0.45
  CCW: 0.28  # ← 低い
  S_shape: 0.25

code_freqs:
  fi:
    "G06V10/82": 12
    "G06V40/16": 10
    "H04N5/232": 8   # カメラ制御（用途コード）
    "G06T7/00": 7    # 画像処理（広義）
    "G06K9/00": 5
```

**診断:**
- 用途コード（H04N5/232）や広義コード（G06T7/00）が混入
- 技術的に本質的なコードに絞る必要

**対処:**

1. **pi_weights.codeを増加:**
```yaml
# rrf_mutate_run
mutate_delta:
  pi_weights:
    code: 0.6  # ← 0.4から増加
```

2. **target_profileを見直し:**
```yaml
target_profile:
  fi:
    "G06V10/82": 1.0
    "G06V40/16": 0.9
    # H04N5/232を除外または低重み
    # G06T7/00を除外または低重み
```

3. **precision laneを強化:**
```yaml
# rrf_mutate_run
mutate_delta:
  lane_weights:
    precision: 1.3
```

**結果:**
```yaml
metrics:
  Fproxy: 0.54  # ← 改善
  CCW: 0.48     # ← 改善
```

### 例2: S_shape高い（semantic dominance）

**初回融合結果:**
```yaml
metrics:
  Fproxy: 0.38
  LAS: 0.52
  CCW: 0.58
  S_shape: 0.62  # ← 高すぎる

lane_contributions:
  recall: 15%
  precision: 20%
  semantic: 65%  # ← 支配的
```

**診断:**
- semantic laneが暴走
- 上位数件にスコアが集中

**対処:**

1. **semantic weightを大幅に減少:**
```yaml
# rrf_mutate_run
mutate_delta:
  weights:
    semantic: 0.4  # ← 0.8から減少
  lane_weights:
    semantic: 0.5  # ← 0.8から減少
```

2. **beta_fuseを減少:**
```yaml
# rrf_mutate_run
mutate_delta:
  beta_fuse: 0.9  # ← 1.2から減少
```

3. **HyDE summaryを見直し（次回Phase1で）:**
- 用途語を削減
- 技術的メカニズムに焦点

**結果:**
```yaml
metrics:
  Fproxy: 0.56    # ← 改善
  S_shape: 0.32   # ← 改善

lane_contributions:
  recall: 35%     # ← バランス改善
  precision: 40%
  semantic: 25%
```

### 例3: recall不足

**初回融合結果:**
```yaml
metrics:
  Fproxy: 0.48
  LAS: 0.35
  CCW: 0.68  # ← 高い（良い）

top_20_candidates:
  A-level: 3件  # ← 少ない
  B-level: 5件
  C-level: 12件

# ユーザ指摘: 「この文献（JP2023-999999）が入ってない」
```

**診断:**
- CCWは高いが、関連文献が少ない
- precision重視すぎてrecall犠牲

**対処:**

1. **recall laneを強化:**
```yaml
# rrf_mutate_run
mutate_delta:
  lane_weights:
    recall: 1.5    # ← 1.0から増加
    precision: 0.8 # ← 1.0から減少
```

2. **指摘文献を確認:**
```yaml
# get_publication
id: "JP2023-999999"
id_type: "pub_id"
```

- FIコード確認 → recall laneのフィルタに含まれているか
- クエリマッチ確認 → synonym不足の可能性

3. **必要に応じてvocabulary_feedbackをやり直し**

**結果:**
```yaml
metrics:
  Fproxy: 0.54  # ← 改善

top_20_candidates:
  A-level: 7件  # ← 改善
```

## まとめ

チューニングの要点:

1. **構造メトリクス**: LAS/CCW/S_shape/Fproxyで品質評価
2. **cheap_path_first**: パラメータ調整優先、新レーン追加は最終手段
3. **rrf_mutate_run**: 低コストで繰り返し試行可能
4. **診断パターン**: low_recall/low_precision/semantic_dominance/approach_imbalanceを識別
5. **review_loop**: max 2 mutate cycles、その後ユーザ確認

次章では、プロンプトメンテナンスガイドを学びます。
