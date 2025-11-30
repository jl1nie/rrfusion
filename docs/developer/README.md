# RRFusion 開発者向けドキュメント

このディレクトリには、RRFusion MCPシステムの開発・保守を担当する開発者向けのドキュメントが含まれています。

## 対象読者

- RRFusionシステムの開発・保守担当者
- MCPサーバの実装者
- バックエンドシステムとの連携担当者
- システムアーキテクトとして全体設計を理解したい方

## システムの位置づけ

RRFusionは、**特許先行技術調査に特化したMVP（Proof of Concept）**です。

**設計方針:**
- 実務検証を目的としたプロトタイプ
- 人手による継続的なメンテナンスを前提
- プロのサーチャーがLLMエージェント経由で利用
- 検索結果を人間が最終レビュー

## ドキュメント構成

### [01. システムアーキテクチャ](./01_architecture.md)
システム全体の構成とコンポーネント間の関係を理解します。

**内容:**
- 3層アーキテクチャ（LLMエージェント / RRFusion MCP / バックエンド）
- コンポーネント間の依存関係
- MVPとしての制約とスケーラビリティ
- システムフロー

### [02. MCPインターフェース](./02_mcp_interface.md)
MCPサーバとして公開するツール群の仕様を学びます。

**内容:**
- MCP（Model Context Protocol）の概要
- 公開ツール一覧とパラメータ仕様
- RunHandle、FusionResult等の返り値構造
- エラーハンドリング

### [03. バックエンドインターフェース](./03_backend_interface.md)
特許データベースおよび検索エンジンとの連携仕様を理解します。

**内容:**
- fulltext検索バックエンドとの連携
- semantic検索バックエンドとの連携
- id_type対応（pub_id/app_doc_id/app_id/exam_id）
- per_field_chars処理

### [04. ストレージ層仕様](./04_storage_layer.md)
特許データの保存・検索に必要なストレージ層の実装要件を学びます。

**内容:**
- fi_norm / fi_full の両方保存要件
- インデックス構造
- field_boosts実装
- filters処理（lop/field/op/value構造）

### [05. 融合エンジン仕様](./05_fusion_engine.md)
RRFusion の核心である融合アルゴリズムの実装仕様を理解します。

**内容:**
- RRF融合アルゴリズム
- 2段階ブースト（fi_norm primary, fi_full secondary）
- target_profileの適用
- weights/lane_weights/pi_weightsの計算
- facet_system実装
- 構造メトリクス計算（LAS/CCW/S_shape/F_struct/Fproxy）

### [06. 各コンポーネント仕様](./06_components.md)
LLMエージェント側で実行される各処理コンポーネントの仕様を学びます。

**内容:**
- feature_extraction処理
- code_profiling処理
- vocabulary_feedback処理
- HyDE summary生成
- user_confirmation_protocol実装

### [07. デプロイとメンテナンス](./07_deployment.md)
システムの構築・運用・監視方法を学びます。

**内容:**
- 環境構築手順
- 依存ライブラリ
- 設定ファイル
- ログとデバッグ
- パフォーマンス監視
- セキュリティ考慮事項

## 推奨学習順序

1. **システム理解**: 01 → 02 → 03 で全体像を把握
2. **実装詳細**: 04 → 05 でコア機能を理解
3. **運用準備**: 06 → 07 でデプロイと保守を学ぶ

## 関連リソース

- SystemPrompt最新版: [prompts/SystemPrompt_v1_5.yaml](../../prompts/SystemPrompt_v1_5.yaml)
- サーチャ向けドキュメント: [../searcher/](../searcher/)
- ソースコード: [src/rrfusion/](../../src/rrfusion/)

## 技術スタック

**想定技術:**
- Python 3.10+
- MCP SDK（Model Context Protocol）
- 特許データベース（PostgreSQL / Elasticsearch 等）
- Semantic検索エンジン（vector database）
- LLMエージェント（Claude 等、MCP経由）

**注:** 具体的な実装はバックエンドシステムに依存します。本ドキュメントではインターフェース仕様を中心に記述します。

## 開発の進め方

### Phase 1: MVP実装
- MCPインターフェースの実装
- 基本的な融合エンジン
- ストレージ層（fi_norm/fi_full対応）

### Phase 2: 機能拡張
- 構造メトリクスの精緻化
- non-JP pipeline対応
- パフォーマンス最適化

### Phase 3: 本番化
- スケーラビリティ改善
- 監視・アラート機能
- 自動テスト整備

## バージョン情報

- ドキュメントバージョン: 1.5
- 対応SystemPromptバージョン: v1.5
- 最終更新: 2025-11-30
