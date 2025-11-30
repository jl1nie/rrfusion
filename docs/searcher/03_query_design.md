# クエリ設計ガイド

本章では、効果的な検索クエリの設計方法を解説します。

## 1. Boolean構文ガイド

### 基本演算子

**AND（論理積）:**
```
顔認証 AND プライバシー保護
```
両方の用語が出現する文献のみヒット

**OR（論理和）:**
```
顔認証 OR 顔識別 OR face recognition
```
いずれかの用語が出現する文献がヒット

**NOT（否定）:**
```
顔認証 NOT 指紋
```
「顔認証」を含むが「指紋」を含まない文献

**デフォルト（演算子なし）:**
```
顔認証 プライバシー保護
```
ANDとして扱われる

### グルーピング

括弧 `()` でグループ化:
```
(顔認証 OR 顔識別) AND (プライバシー保護 OR 暗号化)
```

### フレーズマッチ

ダブルクォート `"..."` で完全一致:
```
"顔認証システム"
```

### ワイルドカード

アスタリスク `*` で任意文字列:
```
認証*
```
→ 認証、認証システム、認証処理 等がヒット

## 2. NEAR演算子の活用（v1.5強化版）

### NEAR構文

**順序なし近接検索:**
```
*N{距離}"用語1 用語2"
```
距離n文字以内に用語1と用語2が出現（順序不問）

**順序あり近接検索:**
```
*ONP{距離}"用語1 用語2"
```
距離n文字以内に用語1→用語2の順で出現

**OR-groupとの組み合わせ:**
```
*N30"(遮蔽 OR マスク) (特徴量 OR 特徴)"
```
括弧内はOR-groupとして扱われる

**制約:**
- NEAR内部はシンプルなOR-groupのみ
- NEAR内にAND/NOT/複雑なネストを含めない

### 使用ガイドライン

**適用レーン:**
- fulltext_precision のみ
- fulltext_wide、fulltext_recallでは使用しない（recall優先）

**使用すべき場面:**
- A要素とA'要素の関連性を確認したい
- 技術的手段（A''）が特定の対象（A'）に適用されることを確認したい
- precision重視で概念の近接性を担保したい

**使用すべきでない場面:**
- recall重視のレーン
- Phase0のwide_search
- ヒット数が少ない場合

### 距離ガイドライン

**日本語:**
- 同一文内: N10-N20
- 同一段落内: N30-N50
- 隣接段落: N80-N100

**英語:**
- 同一文内: N30-N50
- 同一段落内: N80-N120

### 構造パターン

**対象-手段パターン:**
```
*N{30-50}"(対象語群) (手段語群)"
```

例:
```
*N30"(遮蔽 OR マスク) (検出 OR 判定)"
```

**手段-効果パターン:**
```
*N{30-50}"(手段語群) (効果語群)"
```

例:
```
*N30"(重み付け OR 強化) (精度 OR 向上)"
```

### フォールバック戦略

NEARでヒット数が少ない場合:

1. 距離を広げる: N30 → N50 → N80
2. 最終的にNEARを外してAND接続にフォールバック

例:
```
# Step 1: NEAR30で試行
*N30"(遮蔽 OR マスク) (特徴量)"
→ ヒット数 < 20

# Step 2: NEAR50に拡大
*N50"(遮蔽 OR マスク) (特徴量)"
→ ヒット数 < 20

# Step 3: NEARを外してANDに
(遮蔽 OR マスク) AND 特徴量
```

## 3. field_boostsとフィールド指定

### フィールド種別

RRFusionでは以下のフィールドをサポート:

- `title`: タイトル
- `abst`: 要約（abstract）
- `claim`: クレーム
- `desc`: 明細書（description）

**注意:** `abstract`、`description`ではなく、`abst`、`desc`を使用

### field_boostsの設定

各フィールドの重要度を数値で指定:

```yaml
field_boosts:
  title: 80
  abst: 20
  claim: 40
  desc: 40
```

**Phase0 wide_search:**
```yaml
{title: 80, abst: 10, claim: 5, desc: 1}
```
→ タイトル重視、description低重視

**Phase1 representative_hunting:**
```yaml
{title: 80, abst: 20, claim: 40, desc: 40}
```
→ claim/desc重視（実施形態の確認）

**Phase2 recall:**
```yaml
{title: 40, abst: 10, claim: 5, desc: 4}
```
→ バランス型

**Phase2 precision:**
```yaml
{title: 80, abst: 20, claim: 40, desc: 40}
```
→ claim/desc重視

## 4. A/A'/A''/B/C要素の設計原則

### A要素（Core technical mechanisms）

**定義:** 本質的な構成要素・コア技術

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD（広いOR-group）
- Phase2 precision: MUST

**設計原則:**
- 技術的本質を表す用語を選定
- 広すぎず、狭すぎず
- synonym_clusterで同義語・言い換えを網羅

**例:**
```
# Good
(顔認証 OR 顔識別 OR face recognition OR 顔特徴抽出)

# Bad - 広すぎ
(画像処理 OR 認識)

# Bad - 狭すぎ
(CNN顔認証アルゴリズム)
```

### A'要素（Target/condition）

**定義:** 発明が対象とする特徴的な状況・条件

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD
- Phase2 precision: MUST

**設計原則:**
- 発明が解決しようとする「状況」を表現
- 技術的手段（A''）と組み合わせて意味をなす

**例:**
```
# Good
(部分遮蔽 OR マスク OR 顔領域欠損 OR オクルージョン)

# Bad - 一般的すぎ
(入力画像)
```

### A''要素（Technical means）

**定義:** 技術的手段・アプローチ

**クエリでの扱い:**
- Phase1: MUST or strong SHOULD
- Phase2 recall: SHOULD（全approach_categoriesをOR-group）
- Phase2 precision: MUST or strong SHOULD（優先approach）

**設計原則:**
- **複数のapproach_categoriesをカバー**
- OR-groupで幅広くカバー
- 特定のアプローチに偏らない

**approach_categories:**
- enhancement: 強化・増幅系
- selection: 選択・抽出系
- compensation: 補完・推定系
- switching: 切替・代替系
- normalization: 正規化・補正系

**例:**
```
# Good - 複数アプローチをカバー
(重み付け OR 強化 OR 選択 OR 抽出 OR 補完 OR 推定 OR 正規化)

# Bad - 単一アプローチのみ
(重み付け OR 強化)
```

### B要素（Constraints）

**定義:** 重要な限定要素・制約条件

**クエリでの扱い:**
- Phase1: MUST
- Phase2 recall: SHOULD
- Phase2 precision: MUST or strong SHOULD

**設計原則:**
- 技術的に重要な制約・効果
- 発明の特徴を表す条件

**例:**
```
# Good
(プライバシー保護 OR 暗号化 OR ローカル処理)

# Good
(リアルタイム OR 低レイテンシ OR 高速処理)
```

### C要素（Use cases / deployment contexts）

**定義:** 用途・適用シーン

**クエリでの扱い:**
- Phase1: SHOULD（**絶対にMUSTにしない**）
- Phase2 recall: SHOULD（OR-groupのみ）
- Phase2 precision: SHOULD（OR-groupのみ）

**重要な原則: C要素は絶対にMUSTにしない**

理由:
- 同一技術が異なる用途で使われる先行技術を見逃す
- 用途はあくまで例示であり、技術的本質が一致すれば先行技術

**例外:**
- ユーザが明示的に「この用途以外は不要」と指定した場合のみ昇格可
- この場合はuser_confirmation_protocolで確認を取る

**典型的なC要素:**
- ゲート、入退室管理、アクセス制御
- 車載、車両搭載、自動車
- 医療機器、診断装置、ヘルスケア
- 工場、製造ライン、産業用
- 店舗、小売、POS

**例:**
```
# Good - OR-groupのみ
(顔認証) AND (プライバシー保護) AND (ゲート OR 入退室 OR 車載 OR 医療)

# Bad - C要素をANDで縛る
(顔認証) AND (ゲート) AND (入退室管理)
→ 車載用途の顔認証を見逃す
```

### SHOULD実装の2つの方法

**method1: OR-group（推奨）**

```
(A_MUST AND B_MUST) AND (C1 OR C2 OR C3)
```

C1/C2/C3はOR内なので、部分一致でもヒット

**method2: target_profileでブースト**

```yaml
target_profile:
  fi:
    "G06V10/82": 1.0  # A/Bに関連するコード
  ft:
    "5B089AA01": 0.3  # C要素に関連するコード（低い重み）
```

**推奨:** method1（OR-group）をクエリで、method2をfusionで併用

## 5. 分類コードの活用

### FI（File Index）の使い方

**Phase0 (code_profiling):**
- fi_norm のみ使用
- edition symbol（分冊記号）なし
- 例: `G06V10/82`

**Phase1 (representative_hunting):**
- fi_full 使用可
- edition symbol付き可
- 例: `G06V10/82A`, `G06V10/82B`
- 目的: 高精度で代表公報を絞り込む

**Phase2 (batch_retrieval):**
- fi_norm のみ使用（**fi_full禁止**）
- edition symbolなし
- 例: `G06V10/82`
- 理由: edition symbolは割り当てが不安定、recall低下の原因

### フィルタ構文

```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
```

**必須パラメータ:**
- `lop`: 論理演算子（"and" / "or"）
- `field`: フィールド名（"fi" / "ft" / "country" / "date"）
- `op`: 演算子（"in" / ">=" / "<=" / "=" 等）
- `value`: 値（リストまたは単一値）

**注意:** `lop`は必須（省略不可）

### code_system_policy（重要）

**ルール: 1レーンにつき1つの分類体系のみ使用**

**禁止パターン:**
```yaml
# Bad - FI + CPCを同一レーンで
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}
  - {lop: "and", field: "cpc", op: "in", value: ["G06K9/00221"]}
```

**理由:**
- FI/FTは日本特許固有、CPC/IPCは国際標準で粒度・観点が異なる
- 混在させると意図しない絞り込み/漏れが発生
- レーンの役割（recall/precision）が不明確になる

**JP検索の推奨:**
- Primary: FI（FileIndex）
- Secondary: F-Term（構造/用途の補助）
- 避ける: CPC/IPC（ユーザが明示的に非JP要求しない限り）

**非JP検索:**
- Primary: CPC or IPC
- クエリ: 英語
- 別パイプラインとして実行（JP fusionに混ぜない）

## 6. レーン別good/bad examples

### Phase0: fulltext_wide

**Good:**
```yaml
query: "((顔認証 OR 顔識別 OR face recognition) OR (バイオメトリクス OR 生体認証)) AND (遮蔽 OR マスク OR オクルージョン) AND (強化 OR 重み付け OR 選択 OR 補完 OR 正規化)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
field_boosts: {title: 80, abst: 10, claim: 5, desc: 1}
```

**特徴:**
- 広いOR-groups
- 全approach_categoriesを含む
- No NEAR
- C要素をMUSTにしない

**Bad:**
```yaml
query: "顔認証 AND ゲート AND 入退室管理"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}  # edition symbol
```

**理由:**
- 用途語（ゲート/入退室）をANDで縛る → recall低下
- Phase0でedition symbol使用 → code_profiling精度低下

### Phase1: fulltext_precision

**Good:**
```yaml
query: "(顔認証 OR face recognition) AND (遮蔽 OR マスク) AND (特徴量 AND (重み付け OR 強化)) AND (プライバシー保護 OR 暗号化) AND (ゲート OR 入退室 OR アクセス制御)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V40/16B"]}  # edition symbol OK
field_boosts: {title: 80, abst: 20, claim: 40, desc: 40}
```

**特徴:**
- A + A': MUST
- A'': MUST
- B: SHOULD
- C: SHOULD（OR-groupのみ）
- edition symbol使用可

**Good with NEAR:**
```yaml
query: '(顔認証) AND *N30"(遮蔽 OR マスク) (特徴量 OR 特徴)" AND (重み付け OR 強化)'
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}
```

**特徴:**
- NEARでA'とA''の近接性を確認
- precision向上

**Bad:**
```yaml
query: "顔認証 AND ゲート AND 入退室管理 AND 車載"
```

**理由:**
- 複数用途語をANDで縛る → 別用途の関連技術を見逃す

**Bad:**
```yaml
query: '*N30"(遮蔽 AND マスク) OR (特徴量 NOT 指紋)"'
```

**理由:**
- NEAR内部にAND/NOTを含めてはいけない

### Phase2: fulltext_recall

**Good:**
```yaml
query: "((顔特徴抽出 OR 顔認証 OR 顔識別 OR 個人識別) OR (バイオメトリクス)) AND (部分遮蔽 OR マスク OR 顔領域欠損 OR オクルージョン) AND (重み付け OR 強化 OR 選択 OR 抽出 OR 補完 OR 推定 OR 正規化)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}  # fi_norm only
field_boosts: {title: 40, abst: 10, claim: 5, desc: 4}
```

**特徴:**
- Phase1で抽出した語彙を使用
- 全approach_categoriesをOR-groupに
- fi_norm only（edition symbol禁止）
- 複数FIコードでrecall確保
- No NEAR

**Bad:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}  # edition symbol
```

**理由:**
- Phase2でedition symbol使用 → recall低下

### Phase2: fulltext_precision

**Good:**
```yaml
query: "(顔特徴抽出 OR 顔認証) AND (部分遮蔽 OR マスク) AND (特徴量 AND (重み付け OR 強化)) AND (認証精度 OR プライバシー保護) AND (ゲート OR 入退室 OR アクセス制御)"
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}  # fi_norm only
field_boosts: {title: 80, abst: 20, claim: 40, desc: 40}
```

**特徴:**
- A + A': MUST
- A'': MUST or strong SHOULD（優先approach）
- B: SHOULD
- C: SHOULD（OR-groupのみ）
- fi_norm only（edition symbol禁止）

**Good with NEAR:**
```yaml
query: '(顔認証) AND *N30"(遮蔽 OR マスク) (特徴量 OR 特徴)" AND (重み付け OR 強化)'
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}  # fi_norm
```

**Good with negative_hints:**
```yaml
query: "(顔認証) AND (遮蔽 OR マスク) AND (重み付け OR 強化) NOT (指紋 NOT 顔)"
```

**特徴:**
- 簡易なNOT条件で明らかなノイズを除外
- 「指紋のみの文献」を除外、「顔と指紋の組み合わせ」は除外しない

**Bad:**
```yaml
query: "(顔認証) AND (遮蔽) AND (重み付け)"
```

**理由:**
- A''要素が単一アプローチのみ → 他のアプローチ（選択、補完等）を見逃す

### Phase2: semantic (HyDE)

**Good:**
```yaml
text: |
  顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
  マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けまたは補完することで認証精度を維持する。
  プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
feature_scope: "wide"
```

**特徴:**
- Phase1のS_contextから生成
- 1-3段落の自然言語パラグラフ
- 用途語（C_terms）は最小限に

**Bad:**
```yaml
text: "顔認証 ゲート 入退室管理 プライバシー保護"
```

**理由:**
- keyword list、自然言語パラグラフではない

**Bad:**
```yaml
text: "ゲートで使える顔認証技術が欲しいです。プライバシーも保護してください。"
```

**理由:**
- Phase2でraw user text使用（HyDE必須）

## 7. アンチパターン

### query_overconstraining（制約過多）

**パターン1: 長いAND鎖**

```yaml
# Bad
query: "顔認証 AND 遮蔽 AND 重み付け AND プライバシー AND 暗号化 AND ゲート AND 入退室"
```

**対処:**
- MUST要素を2-3個のコア要素に限定
- 補助要素はSHOULD（OR-group）に

```yaml
# Good
query: "(顔認証) AND (遮蔽 OR マスク) AND (重み付け OR 強化 OR 補完) AND (プライバシー OR 暗号化) AND (ゲート OR 入退室 OR アクセス制御)"
```

**パターン2: 用途語をMUST**

```yaml
# Bad
query: "顔認証 AND ゲート AND 入退室管理"
```

**対処:**
- C要素はSHOULD（OR-group）のみ

```yaml
# Good
query: "(顔認証) AND (プライバシー保護) AND (ゲート OR 入退室 OR 車載)"
```

**パターン3: 複雑なNEARネスト**

```yaml
# Bad
query: '*N30"(遮蔽 AND マスク) OR (特徴量 NOT 指紋)"'
```

**対処:**
- NEAR内部はシンプルなOR-groupのみ

```yaml
# Good
query: '*N30"(遮蔽 OR マスク) (特徴量 OR 特徴)"'
```

**パターン4: 単一技術アプローチのみ**

```yaml
# Bad
query: "(顔認証) AND (遮蔽) AND (重み付け)"
```

**対処:**
- 複数approach_categoriesをOR-groupでカバー

```yaml
# Good
query: "(顔認証) AND (遮蔽 OR マスク) AND (重み付け OR 選択 OR 補完 OR 切替 OR 正規化)"
```

### code_misuse（分類コード誤用）

**パターン1: 超狭いコード1つのみ**

```yaml
# Bad
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}
```

**対処:**
- OR-groupで近傍コードを含める

```yaml
# Good
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
```

**パターン2: Phase2でedition symbol**

```yaml
# Bad (Phase2)
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}
```

**対処:**
- Phase2ではfi_normのみ

```yaml
# Good (Phase2)
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}
```

**パターン3: lop省略**

```yaml
# Bad
filters:
  - {field: "fi", op: "in", value: ["G06V10/82"]}
```

**対処:**
- lopは必須

```yaml
# Good
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}
```

## まとめ

クエリ設計の要点:

1. **Boolean構文**: AND/OR/NOTを適切に使い分け
2. **NEAR**: fulltext_precisionでのみ使用、距離ガイドライン遵守
3. **A/A'/A''/B/C要素**: 役割を理解し、C要素は絶対にMUSTにしない
4. **分類コード**: Phase1はfi_full可、Phase2はfi_normのみ
5. **アンチパターン回避**: 制約過多、用途語MUST、NEAR乱用を避ける

次章では、語彙設計と抽出戦略を学びます。
