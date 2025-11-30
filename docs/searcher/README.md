# RRFusion サーチャ向けドキュメント

このディレクトリには、RRFusion MCP システムを使用してプロンプトを継続的に更新・メンテナンスするプロのサーチャー向けのドキュメントが含まれています。

## 対象読者

- 特許調査の実務経験を持つプロフェッショナルサーチャー
- SystemPrompt YAMLを理解・更新する担当者
- RRFusionの検索戦略を設計・改善する方

## ドキュメント構成

### [01. RRFusionのコンセプトと理論](./01_concept.md)
RRFusionの設計思想、理論的バックグラウンド、従来手法との違いを理解します。

**内容:**
- RRFusionの設計思想
- Phase0/1/2パイプラインの必然性
- RRF（Reciprocal Rank Fusion）の基礎理論
- 用語定義（A/A'/A''/B/C要素、recall/precision等）

### [02. パイプライン詳細](./02_pipeline.md)
Phase0/1/2の各フェーズが何をするのか、どのように動作するのかを詳しく学びます。

**内容:**
- Phase0: Feature Extraction & Profiling
- Phase1: Representative Hunting
- Phase2: Batch Retrieval
- 各フェーズのユーザ確認ポイント

### [03. クエリ設計ガイド](./03_query_design.md)
効果的な検索クエリの設計方法を習得します。

**内容:**
- Boolean構文ガイド
- NEAR演算子の活用（v1.5強化版）
- A/A'/A''/B/C要素の設計原則
- good/bad examples（レーン別）

### [04. 語彙設計と抽出戦略](./04_vocabulary_strategy.md)
Phase1からPhase2への語彙フィードバックプロセスを理解します。

**内容:**
- synonym_clusterの設計（core/extended構造）
- vocabulary_feedbackプロセス
- extraction_depthの選択
- approach_categoriesの活用

### [05. FI/F-Term活用ガイド](./05_classification_codes.md)
日本特許分類コードの効果的な活用方法を学びます。

**内容:**
- FI/F-Termの使い分け
- FI edition symbol（分冊記号）の扱い
- Phase1とPhase2での使い分け
- code_system_policy

### [06. 検索結果のチューニング方法](./06_tuning_guide.md)
検索結果の品質を評価し、改善する方法を習得します。

**内容:**
- 構造メトリクス（LAS/CCW/S_shape/Fproxy）の読み方
- cheap_path_first戦略
- rrf_mutate_runの活用
- 診断パターンとその対処法

### [07. プロンプトメンテナンスガイド](./07_maintenance.md)
SystemPrompt YAMLの更新方法とトラブルシューティングを学びます。

**内容:**
- SystemPrompt YAMLの更新方法
- feature_flagsの調整
- mode切替（production/debug/internal_pro）
- 新しい技術分野への適用手順

## 推奨学習順序

1. **初学者**: 01 → 02 → 03 の順で基礎を固める
2. **実践者**: 04 → 05 → 06 で実務スキルを習得
3. **メンテナー**: 07 でプロンプト更新手法を学ぶ

## 関連リソース

- SystemPrompt最新版: [prompts/SystemPrompt_v1_5.yaml](../../prompts/SystemPrompt_v1_5.yaml)
- 開発者向けドキュメント: [../developer/](../developer/)
- 変更履歴: v1.3 → v1.4 → v1.5の変更点は各ドキュメント内で言及

## バージョン情報

- ドキュメントバージョン: 1.5
- 対応SystemPromptバージョン: v1.5
- 最終更新: 2025-11-30
