# RRFusion SystemPrompt 管理

このディレクトリには、RRFusion MCPサーバを使用するLLMエージェント向けのSystemPromptファイルが含まれています。

## 現在の最新版

**SystemPrompt_v1_5.yaml**
- バージョン: v1.5
- 作成日: 2025-11-30
- 状態: **現在の最新版・本番使用推奨**

### 使用方法

**LLMエージェント（Claude等）への設定:**
```yaml
# SystemPromptとして以下のファイルを読み込ませる
prompts/SystemPrompt_v1_5.yaml
```

**環境変数での指定（オプション）:**
```bash
export RRFUSION_SYSTEMPROMPT=/path/to/rrfusion/prompts/SystemPrompt_v1_5.yaml
```

## v1.5の主な機能

### 1. Phase0/1/2パイプライン
- **Phase0**: Feature Extraction & Profiling（技術分野の把握）
- **Phase1**: Representative Hunting（代表公報20-50件取得、語彙抽出）
- **Phase2**: Batch Retrieval（recall/precision/semantic レーン + RRF融合）

### 2. user_confirmation_protocol
統一されたユーザ確認フロー:
- invention_interpretation（Phase0後）
- technical_approach_confirmation（オプション）
- date_range_confirmation（Phase1前）
- representative_review_confirmation（Phase1後）
- fusion_result_confirmation（Phase2後）

### 3. vocabulary_feedback
Phase1の代表公報からPhase2クエリへの語彙フィードバック:
- extraction_depth: primary（高速）/ extended（語彙豊富）
- approach_categories: 5つのカテゴリを均等にOR-groupでカバー

### 4. query_construction_policy
- A/A'/A''/B/C要素の明確な定義
- C要素（用途語）は絶対にMUSTにしない原則
- NEAR演算子活用ガイドライン（v1.5強化）
- negative_hints（除外条件）

### 5. FI/F-Term管理
- Phase0/2: fi_norm（edition symbol除去版）
- Phase1: fi_full（edition symbol付き）使用可
- 2段階ブースト（primary: fi_norm, secondary: fi_full）

## モード切替

SystemPrompt_v1_5.yaml の `mode` 設定:

```yaml
mode: production  # production | debug | internal_pro
```

**production:**
- エンドユーザ（発明者、弁理士）向け
- 高レベルな検索戦略のみ説明

**debug:**
- プロンプトエンジニア向け
- レーン名、クエリ、パラメータを詳細に出力

**internal_pro:**
- 社内専門サーチャー向け
- 検索式構造、FIコード、レーン貢献を日本語で説明

## 過去バージョン（archive/）

### SystemPrompt_v1.4.yaml
- バージョン: v1.4
- 状態: アーカイブ（v1.5に更新済み）
- v1.4の主な変更点:
  - Phase1/Phase2の完全分離
  - FI edition symbol使い分け明確化
  - semantic レーンのHyDE必須化

### SystemPrompt.v1.3.yaml
- バージョン: v1.3
- 状態: アーカイブ（v1.5に更新済み）

### SystemPrompt.ja.yaml
- バージョン: v1.4の日本語補助ドキュメント
- 状態: アーカイブ（v1.5ドキュメントは docs/searcher/ に統合）

## 変更履歴

**v1.3 → v1.4:**
- Phase1/Phase2の完全分離
- FI edition symbol（分冊記号）の使い分け明確化
- semantic レーンのHyDE必須化
- query_construction_policyの統合

**v1.4 → v1.5:**
- user_confirmation_protocol: 統一されたユーザ確認フロー
- vocabulary_design: 構造化された語彙設計ガイド
- technical_approach_coverage: 技術アプローチの多面性をOR-groupでカバー
- vocabulary_feedback: Phase1→Phase2の語彙フィードバックを明確化
- negative_hints: 除外条件の定義と適用ルール
- NEAR演算子活用ガイドラインの拡充
- date調整ポリシーの追加

## 関連ドキュメント

**サーチャ向け（SystemPrompt更新・メンテナンス）:**
- [docs/searcher/](../docs/searcher/)
  - 特に [07_maintenance.md](../docs/searcher/07_maintenance.md) でSystemPrompt更新方法を解説

**開発者向け（MCPサーバ実装）:**
- [docs/developer/](../docs/developer/)

**ドキュメント索引:**
- [DOCUMENTATION.md](../DOCUMENTATION.md)

## メンテナンス方法

SystemPromptの更新手順:

1. **SystemPrompt_v1_5.yamlを編集**
2. **対応するドキュメントを更新**
   - docs/searcher/ の該当章を更新
3. **変更履歴を記録**
   - このREADME.mdに変更点を追記
4. **テスト**
   - サンプル検索で動作確認
   - ポリシー遵守の確認

詳細は [docs/searcher/07_maintenance.md](../docs/searcher/07_maintenance.md) を参照してください。

## バージョン管理のベストプラクティス

**新バージョン作成時:**
1. 現在の最新版を `archive/SystemPrompt_v{X}_{Y}.yaml` にコピー
2. `SystemPrompt_v{X}_{Y+1}.yaml` として新バージョンを作成
3. このREADME.mdを更新
4. 変更点をコミットメッセージに記録

**ファイル命名規則:**
```
SystemPrompt_v{major}_{minor}.yaml
```

例:
- SystemPrompt_v1_5.yaml
- SystemPrompt_v1_6.yaml（次期バージョン）
