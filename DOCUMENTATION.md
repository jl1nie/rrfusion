# RRFusion ドキュメント索引

## 概要

RRFusion（Reciprocal Rank Fusion for Patent Search）は、特許先行技術調査に特化した多段階検索システムです。

**SystemPrompt最新版:** [prompts/SystemPrompt_v1_5.yaml](./prompts/SystemPrompt_v1_5.yaml)

## ドキュメント構成

### サーチャ向けドキュメント

プロのサーチャーがプロンプトを継続的に更新・メンテナンスするためのドキュメント。

**ディレクトリ:** [docs/searcher/](./docs/searcher/)

#### ドキュメント一覧

1. [コンセプトと理論](./docs/searcher/01_concept.md)
   - RRFusionの設計思想
   - Phase0/1/2パイプラインの必然性
   - RRF（Reciprocal Rank Fusion）の基礎理論
   - 用語定義（A/A'/A''/B/C要素等）

2. [パイプライン詳細](./docs/searcher/02_pipeline.md)
   - Phase0: Feature Extraction & Profiling
   - Phase1: Representative Hunting
   - Phase2: Batch Retrieval
   - ユーザ確認ポイント

3. [クエリ設計ガイド](./docs/searcher/03_query_design.md)
   - Boolean構文ガイド
   - NEAR演算子の活用（v1.5強化版）
   - A/A'/A''/B/C要素の設計原則
   - レーン別good/bad examples

4. [語彙設計と抽出戦略](./docs/searcher/04_vocabulary_strategy.md)
   - synonym_clusterの設計（core/extended構造）
   - vocabulary_feedbackプロセス
   - extraction_depthの選択
   - approach_categoriesの活用

5. [FI/F-Term活用ガイド](./docs/searcher/05_classification_codes.md)
   - FI/F-Termの使い分け
   - FI edition symbol（分冊記号）の扱い
   - Phase1とPhase2での使い分け
   - code_system_policy

6. [検索結果のチューニング方法](./docs/searcher/06_tuning_guide.md)
   - 構造メトリクス（LAS/CCW/S_shape/Fproxy）の読み方
   - cheap_path_first戦略
   - rrf_mutate_runの活用
   - 診断パターンとその対処法

7. [プロンプトメンテナンスガイド](./docs/searcher/07_maintenance.md)
   - SystemPrompt YAMLの更新方法
   - feature_flagsの調整
   - mode切替（production/debug/internal_pro）
   - 新しい技術分野への適用手順

### 開発者向けドキュメント

RRFusionシステムの開発・保守を担当する開発者向けのドキュメント。

**ディレクトリ:** [docs/developer/](./docs/developer/)

#### ドキュメント一覧

1. [システムアーキテクチャ](./docs/developer/01_architecture.md)
   - 3層アーキテクチャ（LLMエージェント / RRFusion MCP / バックエンド）
   - コンポーネント間の依存関係
   - MVPとしての制約とスケーラビリティ
   - システムフロー

2. [MCPインターフェース](./docs/developer/02_mcp_interface.md)
   - MCP（Model Context Protocol）の概要
   - 公開ツール一覧とパラメータ仕様
   - RunHandle、FusionResult等の返り値構造
   - エラーハンドリング

3. [バックエンドインターフェース](./docs/developer/03_backend_interface.md)
   - fulltext検索バックエンドとの連携
   - semantic検索バックエンドとの連携
   - id_type対応（pub_id/app_doc_id/app_id/exam_id）
   - per_field_chars処理

4. [ストレージ層仕様](./docs/developer/04_storage_layer.md)
   - fi_norm / fi_full の両方保存要件
   - インデックス構造
   - field_boosts実装
   - filters処理（lop/field/op/value構造）

5. [融合エンジン仕様](./docs/developer/05_fusion_engine.md)
   - RRF融合アルゴリズム
   - 2段階ブースト（fi_norm primary, fi_full secondary）
   - target_profileの適用
   - weights/lane_weights/pi_weightsの計算
   - 構造メトリクス計算（LAS/CCW/S_shape/F_struct/Fproxy）

6. [各コンポーネント仕様](./docs/developer/06_components.md)
   - feature_extraction処理
   - code_profiling処理
   - vocabulary_feedback処理
   - HyDE summary生成
   - user_confirmation_protocol実装

7. [デプロイとメンテナンス](./docs/developer/07_deployment.md)
   - 環境構築手順
   - 依存ライブラリ
   - 設定ファイル
   - ログとデバッグ
   - パフォーマンス監視
   - セキュリティ考慮事項

## アーカイブ

- 過去バージョンの仕様書: [docs/archive/](./docs/archive/)
- 過去バージョンのSystemPrompt: [prompts/archive/](./prompts/archive/)

## バージョン情報

- **現在のバージョン**: v1.5
- **SystemPrompt**: SystemPrompt_v1_5.yaml
- **ドキュメント最終更新**: 2025-11-30

### v1.5の主な変更点

- user_confirmation_protocol: 統一されたユーザ確認フロー
- vocabulary_design: 構造化された語彙設計ガイド
- technical_approach_coverage: 技術アプローチの多面性をOR-groupでカバー
- vocabulary_feedback: Phase1→Phase2の語彙フィードバックを明確化
- negative_hints: 除外条件の定義と適用ルール
- NEAR演算子活用ガイドラインの拡充
- date調整ポリシーの追加

## クイックリンク

**最重要:**
- [SystemPrompt v1.5](./prompts/SystemPrompt_v1_5.yaml)
- [SystemPrompt管理ガイド](./prompts/README.md)
- [サーチャ向けREADME](./docs/searcher/README.md)
- [開発者向けREADME](./docs/developer/README.md)

**コンセプト理解:**
- [01. コンセプトと理論](./docs/searcher/01_concept.md)
- [01. システムアーキテクチャ](./docs/developer/01_architecture.md)

**実装詳細:**
- [README.md](./README.md) - 実装・Docker・テスト関連
