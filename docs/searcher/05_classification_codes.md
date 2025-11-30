# FI/F-Term活用ガイド

本章では、日本特許分類コード（FI・F-Term）の効果的な活用方法を解説します。

## 1. FI（File Index）の基礎

### FIとは

FI（File Index）は、日本特許庁が独自に運用する分類体系です。IPCを基に、より詳細な技術分類を提供します。

**構造:**
```
G06V10/82
│││││││ ││
│││││││ └└─ サブグループ
│││││└─────  メイングループ
│││││
│││└└──────  サブクラス
││└────────  クラス
│└─────────  サブセクション
└──────────  セクション
```

**edition symbol（分冊記号）:**
```
G06V10/82A
         └─ 分冊記号（A/B/C/...）
```

分冊記号は、サブグループをさらに細分化したものです。

### fi_norm vs fi_full

RRFusionでは、FIを2つの形式で扱います。

**fi_norm（正規化版）:**
- edition symbol（分冊記号）を除去
- 例: `G06V10/82`
- 用途: Phase0 code_profiling、Phase2全レーン

**fi_full（完全版）:**
- edition symbol付き
- 例: `G06V10/82A`、`G06V10/82B`
- 用途: Phase1 representative_hunting

## 2. Phase別FI使用ルール

### Phase0: code_profiling

**使用:** fi_norm のみ

**理由:**
- コード分布を広く把握するため
- edition symbolは割り当てが不安定で、統計が偏る

**例:**
```yaml
# Phase0 wide_search
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
```

**get_provenance結果:**
```yaml
target_profile:
  fi:  # fi_norm
    "G06V10/82": 1.0
    "G06V40/16": 0.9
    "G06K9/00": 0.6
```

### Phase1: representative_hunting

**使用:** fi_full 使用可（edition symbol付き）

**理由:**
- 高精度で代表公報を絞り込むため
- Phase1は少数（20-50件）の取得なので、edition symbolの不安定性の影響が小さい

**例:**
```yaml
# Phase1 precision query
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V40/16B"]}
```

**注意:**
- 複数のedition symbolをOR-groupに含めることも可
- 例: `["G06V10/82A", "G06V10/82B", "G06V10/82C"]`

### Phase2: batch_retrieval

**使用:** fi_norm のみ（**fi_full禁止**）

**理由:**
- edition symbolは割り当てが不安定で、recall低下の原因
- Phase2は網羅性重視のため、fi_normでrecall確保

**例:**
```yaml
# Phase2 fulltext_recall
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}

# Phase2 fulltext_precision
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
```

**Bad example:**
```yaml
# Bad - Phase2でfi_full使用
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A"]}  # NG
```

## 3. FIコードの選定戦略

### Phase0での選定

**目標:** 技術分野を広くカバー

**手順:**
1. ユーザ記述からtentative_codesを推定
2. wide_searchで取得
3. get_provenanceでコード分布を分析
4. top 10-20コードを抽出

**選定基準:**
- 頻度上位のコード
- 技術的に関連性の高いコード
- 用途コードに過度に引きずられない

**例:**
```yaml
# Phase0 tentative_codes
tentative_codes:
  fi: ["G06V10/82", "G06V40/16"]

# Phase0 wide_search後のget_provenance結果
code_freqs:
  fi:
    "G06V10/82": 150  # ← 頻度上位
    "G06V40/16": 120
    "G06K9/00": 80
    "G06V40/172": 60
    "G06T7/00": 40
    "H04N5/232": 30  # ← 用途コード（カメラ）、低優先

# target_profileへの反映
target_profile:
  fi:
    "G06V10/82": 1.0
    "G06V40/16": 0.9
    "G06K9/00": 0.6
    "G06V40/172": 0.5
    # H04N5/232は低優先のため除外または低重み
```

### Phase1での選定

**目標:** 代表公報を高精度で絞り込む

**手順:**
1. Phase0のtarget_profileを参考
2. 技術的に本質的なコードに絞る
3. edition symbolを活用して精度向上

**選定基準:**
- Phase0で頻度上位かつ技術的に本質的なコード
- 2-4コード程度に絞る
- edition symbolで細分化

**例:**
```yaml
# Phase1 filters
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V40/16B"]}
```

### Phase2での選定

**目標:** recallとprecisionのバランス

**recall lane:**
- Phase0のtarget_profileから広めに選定
- 5-10コード程度
- fi_normのみ

```yaml
# Phase2 fulltext_recall
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00", "G06V40/172"]}
```

**precision lane:**
- 技術的に本質的なコードに絞る
- 2-4コード程度
- fi_normのみ

```yaml
# Phase2 fulltext_precision
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
```

## 4. F-Term（File Forming Term）の活用

### F-Termとは

F-Termは、FIをさらに細分化した日本独自の分類体系です。技術的観点（構造、機能、材料、用途等）で横断的に分類します。

**構造:**
```
5B089AA01
│││││││││
│││││└└└─ タームコード
│││││
│││└└────  観点
│└└──────  テーマコード
└────────  技術分野
```

### F-Termの使用場面

**通常は使用しない:**
- RRFusionの標準フローでは、FIのみを使用
- F-Termは補助的に使用

**F-Term使用を検討すべき場合:**
- FIだけでは十分に絞り込めない
- 特定の構造・機能に焦点を当てたい
- Phase1で代表公報が多すぎる（> 100件）

### fulltext_problem lane（オプション）

F-Termを活用した問題・構造レーンを追加できます。

**activation_condition:**
- Problem F-Termが3個以上特定できた場合
- または Structure F-Termが明確な場合

**query_style:**
```yaml
query: "(課題語 AND 解決語) OR (構造語 AND 機能語)"
filters:
  - {lop: "and", field: "ft", op: "in", value: ["5B089AA01", "5B089CA13"]}
field_boosts: {title: 40, abst: 20, claim: 10, desc: 10}
```

**注意:**
- F-TermとFIを混在させない（別レーンにする）
- F-Term laneは通常のfulltext laneと並行して使用

## 5. code_system_policy（重要）

### 1レーンにつき1つの分類体系

**ルール:** FI/FT/CPC/IPCを同一レーンで混在させない

**理由:**
- FI/FTは日本特許固有、CPC/IPCは国際標準で粒度・観点が異なる
- 混在させると意図しない絞り込み/漏れが発生
- レーンの役割（recall/precision）が不明確になる

### 禁止パターン

**Bad - FI + CPC混在:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}
  - {lop: "and", field: "cpc", op: "in", value: ["G06K9/00221"]}
```

**Bad - FI + F-Term混在:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82"]}
  - {lop: "and", field: "ft", op: "in", value: ["5B089AA01"]}
```

### 推奨パターン

**JP検索の標準:**
```yaml
# lane1: FIのみ
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}

# lane2: F-Termのみ（オプション）
filters:
  - {lop: "and", field: "ft", op: "in", value: ["5B089AA01", "5B089CA13"]}
```

**非JP検索（別パイプライン）:**
```yaml
# lane1: CPCのみ
filters:
  - {lop: "and", field: "cpc", op: "in", value: ["G06K9/00221", "G06K9/00268"]}
  - {lop: "and", field: "country", op: "in", value: ["US", "EP"]}
```

## 6. JP focus vs non-JP pipeline

### JP検索（デフォルト）

**primary分類:** FI（FileIndex）

**secondary分類:** F-Term（構造/用途の補助）

**避けるべき:** CPC/IPC（ユーザが明示的に非JP要求しない限り）

**理由:**
- FIは日本特許の分類として最も詳細で正確
- JP検索では国内公表/再公表（PCT国内移行）も含まれる
- 多くの案件ではJPパイプラインで十分な国際カバレッジが得られる

**例:**
```yaml
# JP検索の標準設定
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
  - {lop: "and", field: "country", op: "in", value: ["JP"]}
```

### JP検索に含まれる国際出願

**国内公表/再公表:**
- WO出願の日本語翻訳
- 例: 再表2023/123456、特表2023-500001

**したがって:**
- JPパイプラインでPCT出願の日本語版も取得可能
- 多くの案件では非JP展開不要

### 非JP検索（別パイプライン）

**trigger_conditions:**
- JP pipeline（国内公表含む）で十分なA/B候補が得られない場合
- ユーザが明示的にUS/EP原文検索を要求
- 英語圏発の技術で日本語翻訳が不十分と判断される場合

**before_expansion:**
- まずJP検索結果に国内公表/再公表が含まれているか確認
- 国内公表で十分な場合は非JP展開不要
- 展開する場合はuser_confirmation_protocolで確認

**execution_rules:**
- 別パイプラインとして実行（JP fusionに混ぜない）
- CPC/IPC分類を使用（FI/FT使用しない）
- クエリ・semantic textは英語で記述

**例:**
```yaml
# 非JP検索
filters:
  - {lop: "and", field: "cpc", op: "in", value: ["G06K9/00221", "G06K9/00268"]}
  - {lop: "and", field: "country", op: "in", value: ["US", "EP"]}
query: "(face recognition OR facial recognition) AND (occlusion OR mask) AND (weighting OR enhancement)"
```

## 7. 2段階ブースト（融合層での実装）

RRFusionの融合層では、FIコードを2段階でブーストします。

### Primary boost: fi_norm

**役割:** 主要なコード認識ブースト

**実装:** target_profileのfi要素

```yaml
target_profile:
  fi:  # fi_norm
    "G06V10/82": 1.0
    "G06V40/16": 0.9
    "G06K9/00": 0.6
```

### Secondary boost: fi_full

**役割:** 弱いランキングヒント

**実装:** π(d)計算時にfi_fullの一致度を考慮（低い重み）

**効果:**
- Phase1でedition symbolが付いていた文献を若干優遇
- Phase2のrecall低下を防ぎつつ、precision向上に寄与

## 8. 実践例

### 例1: 顔認証（部分遮蔽対応）

**Phase0 tentative_codes:**
```yaml
fi: ["G06V10/82", "G06V40/16"]
```

**Phase0 wide_search後:**
```yaml
target_profile:
  fi:
    "G06V10/82": 1.0  # 画像認識
    "G06V40/16": 0.9  # 顔認証
    "G06K9/00": 0.6   # パターン認識（広義）
```

**Phase1 filters:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82A", "G06V40/16B"]}
```

**Phase2 fulltext_recall:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16", "G06K9/00"]}
```

**Phase2 fulltext_precision:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G06V10/82", "G06V40/16"]}
```

### 例2: 音声認識（ノイズ環境）

**Phase0 tentative_codes:**
```yaml
fi: ["G10L15/20", "G10L21/0208"]
```

**Phase0 wide_search後:**
```yaml
target_profile:
  fi:
    "G10L15/20": 1.0  # 音声認識（特徴抽出）
    "G10L21/0208": 0.9  # ノイズ抑制
    "G10L15/02": 0.6  # 音声認識（一般）
```

**Phase1 filters:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G10L15/20A", "G10L21/0208"]}
```

**Phase2 fulltext_recall:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G10L15/20", "G10L21/0208", "G10L15/02"]}
```

**Phase2 fulltext_precision:**
```yaml
filters:
  - {lop: "and", field: "fi", op: "in", value: ["G10L15/20", "G10L21/0208"]}
```

## まとめ

FI/F-Term活用の要点:

1. **fi_norm vs fi_full**: Phase0/2はfi_norm、Phase1のみfi_full可
2. **Phase別戦略**: Phase0は広く、Phase1は精密に、Phase2は再び広く
3. **code_system_policy**: 1レーンにつき1つの分類体系のみ
4. **JP focus**: FI primary、F-Term secondary、CPC/IPC avoid
5. **非JP検索**: 別パイプラインとして実行、JP fusionに混ぜない
6. **2段階ブースト**: fi_norm primary、fi_full secondary

次章では、検索結果のチューニング方法を学びます。
