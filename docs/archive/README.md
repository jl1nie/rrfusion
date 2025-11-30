# アーカイブドキュメント

このディレクトリには、過去バージョンの仕様書と開発中のドキュメントが含まれています。

## ファイル一覧

### 過去バージョンの仕様書

**RRFusionSpecification.v1.3.md**
- バージョン: 1.3
- 作成日: 2024年頃
- 状態: 非推奨（v1.5に統合済み）

**RRFusionSpec_v1.4_changes.md**
- バージョン: 1.4差分のみ
- 作成日: 2024年後半
- 状態: 非推奨（v1.5に統合済み）
- 注: 中途半端な差分ドキュメントのため、読みにくい

**RRFusionSpecification_old.md**
- 元の場所: `src/rrfusion/RRFusionSpecification.md`
- 大規模な統合仕様書（2227行）
- 状態: v1.5で再構成済み（サーチャ向け・開発者向けに分割）

### 開発過程のドキュメント

**rrfusion_critique.md**
- プロのサーチャー視点からのv1.3への批判
- 用途語への過剰適合問題
- コードprior依存の過剰強化
- 参考資料として保持

**Fusion.md**
- 融合アルゴリズムの詳細仕様（v1.0）
- 構造メトリクスの定義
- 参考資料として保持

## 最新ドキュメント

最新の仕様は以下を参照してください:

### サーチャ向け
- [docs/searcher/](../searcher/)
  - コンセプト、パイプライン、クエリ設計、語彙戦略、FI/F-Term、チューニング、メンテナンス

### 開発者向け
- [docs/developer/](../developer/)
  - アーキテクチャ、MCPインターフェース、バックエンド、ストレージ、融合エンジン、コンポーネント、デプロイ

### SystemPrompt最新版
- [src/rrfusion/SystemPrompt_v1_5.yaml](../../src/rrfusion/SystemPrompt_v1_5.yaml)

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

**v1.3/1.4 → v1.5での再構成:**
- 1つの大きな仕様書（2227行）を2つのドキュメントセットに分割
  - サーチャ向け: プロンプトメンテナンスに必要な知識（7章）
  - 開発者向け: システム実装・保守に必要な仕様（7章）
- 各章を独立した読みやすい単位に分割
- good/bad examplesを大幅に拡充
- 実装例とコード例を追加

詳細は各ドキュメントを参照してください。

## ファイルの用途

- **v1.3/v1.4仕様書**: バージョン履歴の参照用
- **RRFusionSpecification_old.md**: v1.5再構成前の大規模仕様書（参照用）
- **critique**: 設計改善の背景理解
- **Fusion.md**: 融合アルゴリズムの理論的詳細（参照用）

新しい開発・メンテナンスには、[docs/searcher/](../searcher/) および [docs/developer/](../developer/) を使用してください。
