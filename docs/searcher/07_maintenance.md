# プロンプトメンテナンスガイド

本章では、SystemPrompt YAMLの更新方法とトラブルシューティングを解説します。

## 1. SystemPrompt YAMLの構造

### ファイルの場所

**最新版:**
- [prompts/SystemPrompt_v1_5.yaml](../../../prompts/SystemPrompt_v1_5.yaml)

**過去バージョン:**
- SystemPrompt_v1_4.yaml（存在する場合）
- SystemPrompt.ja.yaml（存在する場合）

### YAMLの主要セクション

```yaml
mode: debug  # production | debug | internal_pro

feature_flags:
  enable_multi_run: true
  enable_original_dense: false
  enable_verbose_debug_notes: true
  search_preset: prior_art

agent:
  name: rrfusion_search_agent
  version: v1.5
  role: >
    ...

  tool_selection:
    ...

  global_policies:
    ...

  language_policy:
    ...

user_confirmation_protocol:
  ...

query_construction_policy:
  ...

negative_hints:
  ...

pipeline:
  phase0_feature_extraction:
    ...
  phase1_representative_hunting:
    ...
  phase2_batch_retrieval:
    ...

vocabulary_feedback:
  ...

lane_definitions:
  ...

tool_usage:
  ...

weight_system:
  ...

structural_metrics:
  ...

tuning_policy:
  ...

diagnostic_patterns:
  ...

snippet_policy:
  ...

non_jp_pipeline_policy:
  ...

presentation_policy:
  ...

semantic_feature_presets:
  ...
```

## 2. feature_flagsの調整

### 主要フラグ

**enable_multi_run:**
```yaml
enable_multi_run: true
```
- run_multilane_searchの使用を許可
- Phase2で複数レーンを一括実行
- **推奨:** true（rate limit対策）

**enable_original_dense:**
```yaml
enable_original_dense: false
```
- 従来のdense searchを使用
- **推奨:** false（RRFusion v1.5では使用しない）

**enable_verbose_debug_notes:**
```yaml
enable_verbose_debug_notes: true  # debug mode時のみ
```
- 詳細なデバッグ情報を出力
- **debug mode:** true
- **production mode:** false

**search_preset:**
```yaml
search_preset: prior_art
```
- 検索プリセット
- **prior_art:** 先行技術調査（デフォルト）
- 他のプリセットは将来拡張予定

## 3. modeの切替

### 3つのモード

**production:**
- Researcher persona
- 高レベルな検索戦略のみ説明
- 内部パラメータ・レーン名は出さない
- **対象:** エンドユーザ（発明者、弁理士）

**debug:**
- System-prompt開発者向け
- レーン名、クエリ、パラメータを詳細に出力
- 次の1-2ステップとcoverage/precision問題に焦点
- **対象:** プロンプトエンジニア

**internal_pro:**
- 社内専門サーチャー向け
- 検索式構造、FIコード、各レーンの貢献を日本語で説明
- 低レベル実装詳細は避ける
- **対象:** プロのサーチャー

### モードの切替方法

```yaml
# SystemPrompt_v1_5.yaml
mode: production  # ← ここを変更
```

### モード別の振る舞い

**production mode:**
```
【検索戦略】
顔認証技術の先行技術調査を行います。
まず、関連する技術分野を把握し、代表的な文献を取得します。
その後、詳細な検索を実行して候補をリストアップします。
```

**debug mode:**
```
[Phase0] wide_search
  query: "((顔認証 OR 顔識別) OR (バイオメトリクス)) AND (遮蔽 OR マスク)"
  filters: [{lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}]
  hit_count: 423
  → Phase1へ
```

**internal_pro mode:**
```
【Phase0: 技術分野の把握】
広域検索を実行しました。

クエリ構造:
- コア技術（A）: 顔認証 OR 顔識別 OR バイオメトリクス
- 対象条件（A'）: 遮蔽 OR マスク
- 分類: G06V10/82（画像認識）、G06V40/16（顔認証）

ヒット数: 423件
主要FIコード: G06V10/82 (45%), G06V40/16 (32%), G06K9/00 (18%)

【Phase1へ】
代表公報を30件程度取得し、実際の用語を確認します。
```

## 4. global_policiesの更新

### ポリシーリスト

global_policiesは、LLMエージェントが遵守すべきルールのリストです。

**主要ポリシー:**
```yaml
global_policies:
  - Follow the Phase0 → Phase1 → Phase2 pipeline structure strictly.
  - Phase0: Broad profiling to understand technical field.
  - Phase1: Find 20-50 representative patents using rrf_search_fulltext_raw.
  - Phase2: Batch retrieval using run_multilane_search.
  - In Phase1, edition symbols (fi_full) MAY be used in filters for precision.
  - In Phase2, edition symbols MUST NOT be used in filters (use fi_norm only).
  - In Phase2, semantic lanes MUST use HyDE summaries, NOT raw user text.
  - Default to JP-focused searches (FI/FT codes, Japanese queries).
  - Do not mix code systems (FI+CPC, FI+IPC, etc.) within a single lane.
  - Prefer recall-first design, then tune toward precision using rrf_mutate_run.
  - Treat use-case/deployment terms as C elements (SHOULD/OR), NEVER as MUST.
  - Use user_confirmation_protocol for all confirmations.
  - Maintain 4-lane structure; do NOT add new lanes for query variants.
```

### ポリシーの追加

**例: 新しい制約を追加**

```yaml
global_policies:
  - ...（既存ポリシー）
  - When searching medical device patents, always include relevant safety codes.
  - For automotive patents, consider ISO 26262 functional safety if applicable.
```

### ポリシーの変更

**例: date制限のデフォルトを変更**

```yaml
# Before
- Phase1: Default date range is 10 years.

# After
- Phase1: Default date range is 15 years for foundational technologies, 5 years for rapidly evolving fields.
```

## 5. 新しい技術分野への適用

### ステップ1: tentative_codesの準備

新しい技術分野の主要FI/F-Termコードをリストアップ。

**例: 音声認識（ノイズ環境）**

```yaml
# メモとして記録（SystemPromptには直接含めない）
tentative_codes:
  fi:
    - "G10L15/20"   # 音声認識（特徴抽出）
    - "G10L21/0208" # ノイズ抑制
    - "G10L15/02"   # 音声認識（一般）
  ft:
    - "5D045AA01"   # ノイズ除去
    - "5D045DA13"   # 音響モデル
```

### ステップ2: approach_categoriesの確認

技術分野に応じて、approach_categoriesの適用を確認。

**音声認識の例:**
- enhancement: ノイズ抑制、信号増幅
- selection: 有効フレーム選択
- compensation: 欠損フレーム補間
- switching: 環境適応型アルゴリズム切替
- normalization: 音量正規化

### ステップ3: C要素の識別

用途語を事前にリストアップし、MUST にしないよう注意。

**音声認識の例:**
- C要素: スマートスピーカー、車載、コールセンター、会議システム
- これらは絶対にMUSTにしない

### ステップ4: negative_hintsの定義

技術分野特有の除外条件を定義。

**音声認識の例:**
```yaml
negative_hints:
  - term: "音声合成"
    condition: "NOT (音声合成 AND NOT 認識)"
    exception: "認識と合成の両方を含む場合は除外しない"
    rationale: "合成のみの文献を除外"
```

### ステップ5: 試行とフィードバック

1. Phase0を実行し、コード分布を確認
2. Phase1で代表公報を取得
3. vocabulary_feedbackで用語を抽出
4. Phase2で本検索
5. 結果を評価し、必要に応じてポリシー調整

## 6. トラブルシューティング

### 問題1: Phase1で代表公報が取得できない（< 10件）

**原因:**
- クエリが狭すぎる
- FI edition symbolが厳しすぎる
- date制限が厳しすぎる

**対処:**

1. **クエリを緩和:**
```yaml
# Before
query: "(顔認証) AND (遮蔽 AND マスク) AND (重み付け)"

# After
query: "(顔認証 OR 顔識別) AND (遮蔽 OR マスク) AND (重み付け OR 強化 OR 補完)"
```

2. **FI edition symbolを緩和:**
```yaml
# Before
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}

# After
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V10/82B", "G06V10/82C"]}
```

3. **date制限を緩和:**
```yaml
# Before
filters:
  - {lop: "and", field: "date", op: ">=", value: "2020-01-01"}  # 5年

# After
filters:
  - {lop: "and", field: "date", op: ">=", value: "2010-01-01"}  # 15年
```

### 問題2: Phase2でrecall不足

**原因:**
- FI edition symbolをPhase2で使用している
- FIコードが狭すぎる
- synonymが不足

**対処:**

1. **FI edition symbolの除去を確認:**
```yaml
# Bad
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}  # NG

# Good
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}  # OK
```

2. **FIコードを拡大:**
```yaml
# Before
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}

# After
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
```

3. **vocabulary_feedbackをやり直し:**
- Phase1の代表公報数を増やす
- extended extractionを実行

### 問題3: semantic laneが暴走（S_shape > 0.5）

**原因:**
- HyDE textに用途語が多すぎる
- semantic weightが高すぎる

**対処:**

1. **HyDE textを見直し:**
```yaml
# Before - 用途語が多い
text: "ゲートで使える顔認証技術。入退室管理に適用。"

# After - 技術的メカニズムに焦点
text: "顔認証技術において、マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けすることで認証精度を維持する。"
```

2. **semantic weightを調整:**
```yaml
# weight_system
weights:
  fulltext: 1.0
  semantic: 0.5  # ← 0.8から減少
```

### 問題4: LLMエージェントがポリシーに従わない

**原因:**
- global_policiesの記述が曖昧
- 矛盾するポリシーが存在

**対処:**

1. **ポリシーを明確に:**
```yaml
# Before - 曖昧
- Use edition symbols appropriately.

# After - 明確
- In Phase1, edition symbols (fi_full) MAY be used in filters for precision.
- In Phase2, edition symbols MUST NOT be used in filters (use fi_norm only).
```

2. **矛盾を解消:**
```yaml
# Bad - 矛盾
- Always use edition symbols for precision.
- Never use edition symbols in Phase2.

# Good - 整合
- In Phase1, edition symbols (fi_full) MAY be used.
- In Phase2, edition symbols MUST NOT be used (use fi_norm only).
```

3. **user_confirmation_protocolで確認を追加:**
```yaml
user_confirmation_protocol:
  confirmation_points:
    fi_usage_confirmation:
      when: "Phase1実行前"
      purpose: "FI edition symbolの使用を確認"
      template: |
        【FI分冊記号の使用】
        Phase1では精度向上のため、FI分冊記号（例: G06V10/82A）を使用できます。

        A: 分冊記号を使用（推奨、高精度）
        B: 分冊記号を使用しない（広域カバー）
```

## 7. バージョン管理

### ファイル命名規則

```
SystemPrompt_v{major}_{minor}.yaml
```

**例:**
- SystemPrompt_v1_5.yaml
- SystemPrompt_v1_4.yaml
- SystemPrompt_v1_3.yaml

### 変更履歴の記録

**YAMLファイルの冒頭にコメントで記録:**

```yaml
# RRFusion MCP SystemPrompt v1.5
# ============================================================
#
# v1.5 changes (from v1.4 enhanced v3):
#   - user_confirmation_protocol: 統一されたユーザ確認フローを新設
#   - vocabulary_design: 構造化された語彙設計ガイドを追加
#   - technical_approach_coverage: 技術アプローチの多面性をOR-groupでカバー
#   - vocabulary_feedback: Phase1→Phase2の語彙フィードバックを明確化
#   - negative_hints: 除外条件の定義と適用ルールを新設
#   - near_ops強化: NEAR活用ガイドラインを拡充
#   - date_adjustment_policy: Phase1のdate動的調整ルールを追加
#   - レーン数は維持（4レーン: wide/recall/precision/semantic）
#
# ============================================================
```

### マイグレーション

**v1.4 → v1.5へのマイグレーション例:**

1. **user_confirmation_protocolの追加:**
   - 既存の確認フローをuser_confirmation_protocolに統合

2. **vocabulary_feedbackの構造化:**
   - extraction_depthの設定を追加
   - approach_categoriesの適用ルールを明確化

3. **negative_hintsの定義:**
   - 技術分野ごとに除外条件を定義

4. **NEAR演算子ガイドラインの強化:**
   - 距離ガイドラインを追加
   - フォールバック戦略を明記

## 8. ドキュメントとの整合性

### SystemPrompt YAML ⇔ ドキュメント

**重要:** SystemPrompt YAMLを更新したら、ドキュメントも更新。

**対応表:**

| SystemPrompt セクション | ドキュメント |
|----------------------|------------|
| query_construction_policy | 03_query_design.md |
| vocabulary_feedback | 04_vocabulary_strategy.md |
| pipeline.phase1 | 02_pipeline.md, 05_classification_codes.md |
| weight_system | 06_tuning_guide.md |
| diagnostic_patterns | 06_tuning_guide.md |
| user_confirmation_protocol | 02_pipeline.md |

### 更新手順

1. SystemPrompt YAMLを更新
2. 対応するドキュメントを更新
3. README.mdのバージョン情報を更新
4. 変更履歴を記録（CHANGELOG.mdまたはコミットメッセージ）

## 9. テスト・検証

### 新しいSystemPromptの検証

**ステップ1: サンプル検索で動作確認**
- 既知の技術分野で検索実行
- Phase0/1/2が正常に動作するか確認

**ステップ2: ポリシー遵守の確認**
- Phase2でedition symbol使用していないか
- C要素をMUSTにしていないか
- user_confirmation_protocolを使用しているか

**ステップ3: メトリクスの確認**
- Fproxy >= 0.5を達成できるか
- LAS/CCWが健全範囲か

**ステップ4: ドキュメントとの整合性確認**
- ドキュメントの記述とSystemPromptが一致しているか

### レグレッションテスト

**以前のバージョンとの比較:**
- 同じ検索タスクを旧版と新版で実行
- 結果の品質を比較
- 改善されているか、劣化していないか確認

## 10. コミュニティフィードバック

### フィードバックの収集

**ソース:**
- エンドユーザ（発明者、弁理士）
- プロのサーチャー
- プロンプトエンジニア

**収集方法:**
- 検索セッション後のアンケート
- GitHub Issues
- 社内フィードバックフォーム

### フィードバックの反映

**優先順位:**
1. **Critical:** システムが動作しない、明らかな誤動作
2. **High:** recall/precision大幅低下、user experience悪化
3. **Medium:** 改善提案、新機能要望
4. **Low:** 微調整、ドキュメント改善

**反映プロセス:**
1. フィードバック収集
2. 優先順位付け
3. SystemPrompt更新案の作成
4. テスト・検証
5. ドキュメント更新
6. リリース

## まとめ

プロンプトメンテナンスの要点:

1. **feature_flags**: enable_multi_run=true推奨
2. **mode切替**: production/debug/internal_proを適切に使い分け
3. **global_policies**: 明確で矛盾のないポリシーを記述
4. **新技術分野**: tentative_codes準備、approach_categories確認、C要素識別
5. **トラブルシューティング**: 症状別の対処法を把握
6. **バージョン管理**: 変更履歴を記録、マイグレーション手順を明確に
7. **ドキュメント整合性**: SystemPrompt更新時は必ずドキュメントも更新
8. **テスト・検証**: サンプル検索で動作確認、レグレッションテスト実施

---

以上で、サーチャ向けドキュメントは完了です。

次に進むべきこと:
- [開発者向けドキュメント](../developer/)の作成
- SystemPromptの継続的改善
- 新しい技術分野への適用実験
