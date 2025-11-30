# 語彙設計と抽出戦略

本章では、Phase1からPhase2への語彙フィードバックプロセスと、効果的な語彙設計戦略を解説します。

## 1. synonym_clusterの設計

### core/extended 2層構造

RRFusionの語彙は、以下の2層構造で管理されます。

```yaml
synonym_clusters:
  core:      # Phase0で構築
    ...
  extended:  # Phase1で追加
    ...
```

#### core層（Phase0で構築）

**定義:** 基本的な同義語・言い換え

**情報源:**
- 技術用語辞典的な同義語
- 日英対訳
- 略語・正式名称
- カタカナ表記バリエーション

**例:**
```yaml
core:
  face_recognition:
    - "顔認証"
    - "顔識別"
    - "face recognition"
    - "facial recognition"
  occlusion:
    - "遮蔽"
    - "マスク"
    - "オクルージョン"
    - "occlusion"
```

**使用場面:**
- Phase0 wide_search

#### extended層（Phase1で追加）

**定義:** 実際の特許文献で使われる表現

**情報源:**
- 代表公報のclaim/abstractから抽出
- 上位概念・下位概念
- 機能的表現・構造的表現の両方

**例:**
```yaml
extended:
  face_recognition:
    - "顔特徴抽出"  # [JP2023-123456]
    - "顔画像解析"  # [JP2023-234567]
    - "個人識別"    # [JP2023-345678]
    - "照合処理"    # [JP2023-456789]
  occlusion:
    - "部分遮蔽"      # [JP2023-123456]
    - "顔領域欠損"    # [JP2023-234567]
    - "マスク装着"    # [JP2023-345678]
    - "遮蔽状態"      # [JP2023-456789]
```

**使用場面:**
- Phase2 fulltext_recall（core + extended全体）
- Phase2 fulltext_precision（core + 高頻度extended）

### coverage_checklist（語彙網羅性チェック）

語彙設計時に以下をチェック:

- [ ] 日本語表現と英語表現の両方を含むか
- [ ] カタカナ表記のバリエーションを含むか
- [ ] 技術的な言い換え（機能的/構造的）を含むか
- [ ] 上位概念（より抽象的な表現）を含むか
- [ ] 下位概念（より具体的な表現）を含むか
- [ ] approach_categoriesの該当カテゴリを網羅しているか

**例: 機能的 vs 構造的表現**

| 機能的表現 | 構造的表現 |
|-----------|-----------|
| 照合する | 照合部 |
| 抽出する | 抽出手段 |
| 判定する | 判定器 |
| 強化する | 強化回路 |

両方を含めることで、recall向上。

## 2. technical_approach_coverage（技術アプローチの多面性）

### approach_categories

発明の技術的手段（A''要素）は、複数のアプローチで実現可能な場合が多い。

**5つのカテゴリ:**

#### 1. enhancement（強化・増幅系）

**用語例:**
- 強化、増強、強調
- ブースト、重み付け、重み増加
- 加重平均、スコア増加

**適用例:**
- 非遮蔽領域の特徴量を強化
- 信頼度の高い特徴のスコアを増加

#### 2. selection（選択・抽出系）

**用語例:**
- 選択、抽出、選定
- 部分的使用、有効領域、可視領域
- フィルタリング、絞り込み

**適用例:**
- 非遮蔽領域のみを選択的に使用
- 信頼度の高い特徴のみ抽出

#### 3. compensation（補完・推定系）

**用語例:**
- 補完、補填、推定
- 復元、再構成、補償
- 予測、生成

**適用例:**
- 遮蔽領域の特徴を推定
- 欠損部分を補完

#### 4. switching（切替・代替系）

**用語例:**
- 切り替え、代替、フォールバック
- 置換、変更、移行
- モード切替

**適用例:**
- 遮蔽時は別アルゴリズムに切替
- 信頼度に応じて処理を変更

#### 5. normalization（正規化・補正系）

**用語例:**
- 正規化、補正、調整
- スケーリング、キャリブレーション
- 平準化

**適用例:**
- 特徴量を正規化
- スコアを補正

### 適用ルール

**原則: すべてのカテゴリをOR-groupでカバー**

```yaml
# A''要素の設計
A_double_prime_terms:
  query: "(強化 OR 重み付け OR 選択 OR 抽出 OR 補完 OR 推定 OR 切替 OR 正規化)"
```

**レーンは増やさない**

悪い例:
```
# Bad - アプローチ別に別レーンを作成
lanes:
  - enhancement_lane
  - selection_lane
  - compensation_lane
```

良い例:
```
# Good - 単一クエリ内のOR構造で対応
query: "(顔認証) AND (遮蔽 OR マスク) AND (強化 OR 選択 OR 補完 OR 切替 OR 正規化)"
```

### ユーザ確認: technical_approach_confirmation

複数のアプローチが想定される場合、ユーザに重視するアプローチを確認できます。

```
【技術アプローチの確認】
この発明の技術的手段として、複数のアプローチが考えられます。

A: 強化・重み付け（特徴量の重みを増加させる）
B: 選択的使用（有効な領域のみを選択して使用）
C: 補完・推定（欠損部分を推定・復元する）
D: すべてを均等にカバー（推奨）
```

**結果の反映:**
- D選択時: すべてのカテゴリを均等にOR-groupに
- A/B/C選択時: 選択されたカテゴリをMUSTに近い扱い、他をSHOULD

## 3. vocabulary_feedbackプロセス

### 全体フロー

```
Phase1完了
  ↓
Step1: peek_snippets（代表公報取得）
  ↓
Step2: 語彙抽出（LLM推論）
  ├─ primary extraction（20-30件、title/abst/claim）
  └─ [必要に応じて] extended extraction（10件、desc含む）
  ↓
Step3: synonym_clusterの更新
  ↓
Step4: Phase2クエリの再構築
  ↓
Step5: ドキュメント化
```

### Step1: peek_snippets

**primary extraction:**
```yaml
parameters:
  count: 20-30
  fields: ["title", "abst", "claim"]
```

**extended extraction（条件付き）:**
```yaml
parameters:
  count: 10
  fields: ["title", "abst", "claim", "desc"]
  per_field_chars:
    desc: 1000  # 冒頭1000文字
```

### Step2: 語彙抽出（LLM推論）

#### primary extraction（常に実行）

**抽出対象:**

**A_terms（コア技術用語）:**
- 焦点: 動作・構造・機能を表す名詞・動詞句
- 例: "顔特徴抽出"、"照合処理"、"個人識別"

**A_prime_terms（対象・条件用語）:**
- 焦点: 発明が対象とする特徴的な状況・条件
- 例: "部分遮蔽"、"マスク装着"、"顔領域欠損"

**B_terms（制約・効果用語）:**
- 焦点: 制約条件や達成される効果
- 例: "認証精度"、"プライバシー保護"、"暗号化処理"

**S_context（semantic用の技術的文脈）:**
- 焦点: 用途語を含めず、技術的メカニズムに焦点
- 形式: 1-3段落の自然言語
- 例: "カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。部分遮蔽時には非遮蔽領域の特徴を活用する。"

**品質チェック:**
- A_termsが3個以上 → OK
- A''_termsが3個以上 → OK、未満ならextended extractionへ
- approach_categoriesが1つに偏っていない → OK、偏っていればextended extractionへ

#### extended extraction（条件付き）

**トリガー条件:**
- primary抽出でA''要素（技術的手段）が3個未満
- approach_categoriesが1カテゴリのみに偏っている
- ユーザが明示的に拡張抽出を要求

**抽出対象:**

**A''_terms（技術的手段用語）:**
- 情報源: 【発明を実施するための形態】、【課題を解決するための手段】、【発明の効果】
- 焦点: approach_categoriesを参照し、カテゴリ別に抽出
- マーク: [ext]を付与

**抽出例:**
```yaml
A_double_prime_terms:
  enhancement:
    - "重み増加 [ext, JP2023-123456]"
    - "強調処理 [ext, JP2023-234567]"
  selection:
    - "選択的抽出 [ext, JP2023-123456]"
    - "有効領域抽出 [ext, JP2023-345678]"
  compensation:
    - "補完処理 [ext, JP2023-234567]"
    - "推定復元 [ext, JP2023-456789]"
```

### Step3: synonym_clusterの更新

**ルール:**
- 既存のcoreと重複する用語は追加しない
- 抽出元の公報番号を記録
- approach_categoriesのカテゴリを付与
- extended抽出で追加した用語には[ext]マークを付与

**更新例:**
```yaml
synonym_clusters:
  core:
    face_recognition: ["顔認証", "顔識別", "face recognition"]
  extended:
    face_recognition:
      - {term: "顔特徴抽出", source: "JP2023-123456", category: "A"}
      - {term: "照合処理", source: "JP2023-234567", category: "A"}
      - {term: "個人識別", source: "JP2023-345678", category: "A"}
    technical_means:
      - {term: "重み増加", source: "JP2023-123456", category: "A''", approach: "enhancement", ext: true}
      - {term: "選択的抽出", source: "JP2023-234567", category: "A''", approach: "selection", ext: true}
```

### Step4: Phase2クエリの再構築

#### fulltext_recall

**使用語彙:** core + extended 全体

```yaml
query: |
  ((顔認証 OR 顔識別 OR face recognition OR 顔特徴抽出 OR 照合処理 OR 個人識別) OR
   (バイオメトリクス OR 生体認証))
  AND
  (遮蔽 OR マスク OR オクルージョン OR 部分遮蔽 OR 顔領域欠損 OR マスク装着)
  AND
  (重み付け OR 強化 OR 重み増加 OR 強調処理 OR
   選択 OR 抽出 OR 選択的抽出 OR 有効領域抽出 OR
   補完 OR 推定 OR 補完処理 OR 推定復元 OR
   正規化 OR 補正)
```

**特徴:**
- すべてのsynonym_clusterを使用
- 全approach_categoriesをOR-groupに
- A/A'/A''/B: SHOULD（広いOR-group）
- C: SHOULD（OR-groupのみ）

#### fulltext_precision

**使用語彙:** core + 高頻度extended

```yaml
query: |
  (顔特徴抽出 OR 顔認証)
  AND
  (部分遮蔽 OR マスク)
  AND
  (特徴量 AND (重み付け OR 強化 OR 重み増加))
  AND
  (認証精度 OR プライバシー保護)
  AND
  (ゲート OR 入退室 OR アクセス制御)
```

**特徴:**
- core + Phase1で高頻度だった用語を優先
- A + A': MUST
- A'': MUST or strong SHOULD（優先approach）
- B: SHOULD
- C: SHOULD（OR-groupのみ）
- NEAR使用可

#### semantic (HyDE)

**使用語彙:** S_context + A_terms + A_prime summary

```yaml
text: |
  顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
  マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けまたは補完することで認証精度を維持する。
  プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
feature_scope: "wide"
```

**制約:**
- 用途語（C_terms）は最小限に
- 1-3段落の自然言語パラグラフ
- raw user textやkeyword listは禁止

### Step5: ドキュメント化

**記録すべき内容:**
- 抽出した用語リスト（カテゴリ別）
- 抽出元の代表公報番号
- Phase1クエリとPhase2クエリの差分
- 追加した用語の根拠
- extended抽出を実行したか否かとその理由

**目的:** 再現性確保、後続の改善に活用

## 4. extraction_depth（抽出深度）の選択

### primary vs extended のトレードオフ

| 項目 | primary | extended |
|------|---------|----------|
| 対象フィールド | title/abst/claim | title/abst/claim/desc |
| 対象件数 | 20-30件 | 10件 |
| 目的 | A/A'/B要素の基本語彙 | A''要素の補完 |
| 推論コスト | 低 | 中〜高 |
| 語彙豊富さ | 標準 | 豊富 |

### extraction_depthの決定フロー

```
Phase1完了
  ↓
primary extraction実行（20-30件）
  ↓
品質チェック
  ├─ A''_terms >= 3個 → Phase2へ
  ├─ approach_categoriesが均等 → Phase2へ
  └─ 上記未満 → extended extraction実行
      ↓
      extended extraction（10件、desc含む）
      ↓
      Phase2へ
```

### auto_trigger（自動トリガー）

**デフォルト設定:**
```yaml
extraction_depth:
  auto_trigger: true
```

**トリガー条件:**
- primary抽出でA''要素（技術的手段）が3個未満
- approach_categoriesが1カテゴリのみに偏っている

この条件に該当する場合、自動的にextended extractionを実行。

### ユーザ確認: vocabulary_depth_confirmation（オプション）

通常はauto_triggerで自動判定するため省略可能ですが、以下の場合にユーザ確認を取ることができます。

**トリガー条件:**
- approach_categoriesが複雑
- 実装バリエーションが多い技術分野

```
【語彙抽出の深さ】
代表公報から検索語彙を抽出します。

A: 標準（クレーム・要約のみ）- 高速、基本語彙
B: 拡張（実施形態も含む）- 語彙豊富だが時間がかかる

技術的手段のバリエーションが多い場合は B が有効です。
不明な場合は A で進め、不足時に自動で拡張します。
```

## 5. quality_check（品質チェック）

### primary抽出後のチェック

- [ ] A_termsが3個以上抽出されているか
- [ ] A''_termsが3個以上抽出されているか → 未満ならextended抽出をトリガー
- [ ] approach_categoriesが1つに偏っていないか → 偏っていればextended抽出をトリガー

### Phase2実行前のチェック

- [ ] C_terms（用途語）がA/A'/A''に混入していないか
- [ ] synonym_clusterが十分に更新されているか
- [ ] 各approach_categoryに用語が最低2個以上あるか

### feedback_loop（フィードバックループ）

**条件:** Phase2結果のprecisionが低い場合

**アクション:** vocabulary_feedbackをやり直し、用語の精度を上げる

**手順:**
1. Phase2のget_provenanceでCCW/LASを確認
2. CCW < 0.3の場合、分類が散乱している
3. peek_snippetsで上位候補を確認
4. 無関連文献が多い場合、vocabulary_feedbackをやり直し
5. A/A'要素を絞り込み、B要素を強化

## 6. negative_hints（除外条件）

### 定義ガイドライン

**定義すべき場面:**
- 技術的に明らかに異なる分野
- 同じ用語が別の意味で使われる分野
- 発明の目的と異なる目的の文献

**定義構造:**
```yaml
negative_hints:
  - term: "除外対象の用語"
    condition: "NOT句の構造"
    exception: "除外しない例外条件"
    rationale: "除外する理由"
```

**例:**
```yaml
negative_hints:
  - term: "表情認識"
    condition: "NOT (表情認識 AND NOT (本人認証 OR 個人認証))"
    exception: "認証目的で表情を使う場合は除外しない"
    rationale: "感情分析のみの文献を除外"

  - term: "指紋"
    condition: "NOT (指紋 NOT 顔)"
    exception: "顔と指紋の組み合わせは除外しない"
    rationale: "指紋のみの文献を除外"
```

### 適用ポリシー

**Phase0 wide:**
- 適用しない
- 理由: recallを最大化

**Phase1 representative:**
- オプション
- 明らかなノイズが多い場合のみ簡易なNOT条件を適用

**Phase2 recall:**
- 適用しない
- 理由: recall重視

**Phase2 precision:**
- 推奨
- 簡易なNOT条件を適用可
- ただし複雑な条件は避け、post-filteringで対応

**post-filtering:**
- fusion後のスニペットレビュー時
- negative_hintsに該当する文献をマーク
- 人間レビューで最終判断

### 共通パターン

**パターン1: 関連技術だが異なる目的**

```
template: "NOT (関連用語 AND NOT (本発明の目的語))"
example: "NOT (顔検出 AND NOT (認証 OR 照合 OR 識別))"
```

**パターン2: 同じ用語の別分野**

```
template: "NOT (分野限定語 AND NOT (本発明の分野語))"
example: "NOT (画像表示 AND NOT 認証)"
```

**パターン3: 上位概念のうち除外すべき下位概念**

```
template: "NOT (下位概念 NOT 上位概念)"
example: "NOT (指紋 NOT 顔)"
```

## まとめ

語彙設計と抽出戦略の要点:

1. **synonym_cluster**: core/extended 2層構造で管理
2. **approach_categories**: 5つのカテゴリをOR-groupで均等にカバー
3. **vocabulary_feedback**: primary → extended の段階的抽出
4. **extraction_depth**: auto_triggerで自動判定、必要に応じてextended実行
5. **quality_check**: 各段階で品質チェック、不足時は再抽出
6. **negative_hints**: precision laneで簡易なNOT条件、post-filteringで最終判断

次章では、FI/F-Term活用ガイドを学びます。
