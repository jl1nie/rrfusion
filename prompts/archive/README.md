# SystemPrompt アーカイブ

このディレクトリには、過去バージョンのSystemPromptファイルが含まれています。

## ファイル一覧

### SystemPrompt_v1.4.yaml
- **元の名前**: SystemPrompt.yaml
- **バージョン**: v1.4
- **作成日**: 2024年後半
- **状態**: アーカイブ（v1.5に更新済み）

**v1.4の主な機能:**
- Phase1/Phase2の完全分離
- FI edition symbol使い分け明確化
- semantic レーンのHyDE必須化
- query_construction_policyの統合

### SystemPrompt.v1.3.yaml
- **バージョン**: v1.3
- **作成日**: 2024年前半
- **状態**: アーカイブ（v1.5に更新済み）

**v1.3の主な機能:**
- 基本的なPhase0/1/2パイプライン
- RRF融合
- 構造メトリクス

**v1.3の問題点（rrfusion_critique.mdより）:**
- 用途語への過剰適合問題
- コードprior依存の過剰強化
- → v1.4/v1.5で改善

### SystemPrompt.ja.yaml
- **バージョン**: v1.4の日本語補助ドキュメント
- **作成日**: 2024年後半
- **状態**: アーカイブ（v1.5ドキュメントは docs/searcher/ に統合）

**用途:**
- 特許サーチャーがSystemPromptの設計意図を理解するための補助資料
- v1.5では docs/searcher/ に統合され、より包括的なドキュメントに進化

## 最新版の使用

**現在の最新版:**
- [../SystemPrompt_v1_5.yaml](../SystemPrompt_v1_5.yaml)

**ドキュメント:**
- サーチャ向け: [docs/searcher/](../../docs/searcher/)
- 開発者向け: [docs/developer/](../../docs/developer/)

## バージョン間の主な変更点

### v1.3 → v1.4
1. Phase1/Phase2の完全分離
2. FI edition symbol（分冊記号）の使い分け明確化
3. semantic レーンのHyDE必須化
4. query_construction_policyの統合
5. レーン別good/bad examplesの追加

### v1.4 → v1.5
1. user_confirmation_protocol: 統一されたユーザ確認フロー
2. vocabulary_design: 構造化された語彙設計ガイド
3. technical_approach_coverage: 技術アプローチの多面性をOR-groupでカバー
4. vocabulary_feedback: Phase1→Phase2の語彙フィードバックを明確化
5. negative_hints: 除外条件の定義と適用ルール
6. NEAR演算子活用ガイドラインの拡充
7. date調整ポリシーの追加

## アーカイブファイルの用途

- **バージョン履歴の参照**
- **変更点の比較**
- **過去のシステム動作の再現**（必要な場合）

新しい開発・メンテナンスには、最新版 [../SystemPrompt_v1_5.yaml](../SystemPrompt_v1_5.yaml) を使用してください。
