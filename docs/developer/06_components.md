# 各コンポーネント仕様

本章では、LLMエージェント側で実行される各処理コンポーネントの仕様を解説します。

## 1. feature_extraction処理

### 概要

ユーザの発明記述から技術要素（A/A'/A''/B/C）を抽出します。

### 入力

```python
user_input: str  # ユーザの発明記述（自然言語）
```

### 処理

**LLM推論による抽出:**
- A要素: コア技術（Core technical mechanisms）
- A'要素: 対象・条件（Target/condition）
- A''要素: 技術的手段（Technical means）
- B要素: 制約条件（Constraints）
- C要素: 用途（Use cases）

**synonym_cluster構築（core）:**
- 技術用語辞典的な同義語
- 日英対訳
- カタカナ表記バリエーション

**tentative_codes推定:**
- FI/F-Termコードの暫定推定

### 出力

```python
FeatureSet {
    A_terms: List[str],
    A_prime_terms: List[str],
    A_double_prime_terms: List[str],
    B_terms: List[str],
    C_terms: List[str],
    synonym_clusters: {
        core: Dict[str, List[str]]
    },
    tentative_codes: {
        fi: List[str],
        ft: List[str]
    }
}
```

### 実装方針

**LLMプロンプト例:**
```
以下の発明記述から技術要素を抽出してください。

【発明記述】
{user_input}

【抽出対象】
- A要素（コア技術）: 本質的な構成要素・技術メカニズム
- A'要素（対象・条件）: 発明が対象とする状況・条件
- A''要素（技術的手段）: 具体的なアプローチ・手段
- B要素（制約条件）: 重要な限定要素
- C要素（用途）: 適用シーン・用途

【出力形式】
JSON形式で出力
```

## 2. code_profiling処理

### 概要

Phase0 wide_search結果からFI/F-Termコード分布を分析し、target_profileを構築します。

### 入力

```python
run_id: str  # Phase0 wide_searchのrun_id
```

### 処理

**get_provenanceでコード頻度取得:**
```python
provenance = get_provenance(run_id)
code_freqs = provenance["code_freqs"]
# {"fi": {"G06V10/82": 150, "G06V40/16": 120, ...}}
```

**target_profile構築:**
- top 10-20コードを抽出
- 頻度に基づいて重み算出
- 用途コードに過度に引きずられないよう調整

### 出力

```python
TargetProfile {
    fi: Dict[str, float],  # FIコード → 重み
    ft: Dict[str, float]   # F-Termコード → 重み
}
```

### 実装例

```python
def build_target_profile(code_freqs: Dict[str, Dict[str, int]], top_n: int = 15) -> TargetProfile:
    """
    Build target_profile from code frequencies
    """
    # Sort by frequency
    fi_sorted = sorted(code_freqs["fi"].items(), key=lambda x: x[1], reverse=True)
    ft_sorted = sorted(code_freqs["ft"].items(), key=lambda x: x[1], reverse=True)

    # Top-N codes
    top_fi = fi_sorted[:top_n]
    top_ft = ft_sorted[:top_n]

    # Normalize weights (max=1.0)
    max_fi_freq = top_fi[0][1] if top_fi else 1
    max_ft_freq = top_ft[0][1] if top_ft else 1

    fi_profile = {code: freq / max_fi_freq for code, freq in top_fi}
    ft_profile = {code: freq / max_ft_freq for code, freq in top_ft}

    return TargetProfile(fi=fi_profile, ft=ft_profile)
```

## 3. vocabulary_feedback処理

### 概要

Phase1の代表公報から実際の特許用語を抽出し、synonym_clusterを更新します。

### 入力

```python
run_id: str              # Phase1 representative_huntingのrun_id
extraction_depth: str    # "primary" | "extended"
```

### 処理フロー

**Step1: peek_snippets**
```python
snippets = peek_snippets(run_id, count=20-30, fields=["title", "abst", "claim"])
# extended の場合: fields=["title", "abst", "claim", "desc"], per_field_chars={"desc": 1000}
```

**Step2: LLM推論による語彙抽出**
- A_terms: コア技術用語
- A_prime_terms: 対象・条件用語
- A''_terms: 技術的手段用語（approach_categories別）
- B_terms: 制約・効果用語
- S_context: semantic用の技術的文脈

**Step3: synonym_cluster更新**
```python
synonym_clusters["extended"] = extracted_vocabulary
```

**Step4: Phase2クエリ再構築**
- fulltext_recall: core + extended全体
- fulltext_precision: core + 高頻度extended
- semantic (HyDE): S_context + A_terms + A_prime summary

### 出力

```python
VocabularyFeedback {
    updated_synonym_clusters: Dict,
    phase2_queries: {
        fulltext_recall: str,
        fulltext_precision: str,
        semantic_hyde: str
    },
    extracted_terms: {
        A_terms: List[str],
        A_prime_terms: List[str],
        A_double_prime_terms: Dict[str, List[str]],  # approach_category別
        B_terms: List[str],
        S_context: str
    }
}
```

### LLMプロンプト例

```
以下の代表公報から検索語彙を抽出してください。

【代表公報スニペット】
{snippets}

【抽出対象】
- A_terms: コア技術用語（動作・構造・機能）
- A_prime_terms: 対象・条件用語
- A''_terms: 技術的手段用語（以下のカテゴリ別）
  - enhancement: 強化・増幅系
  - selection: 選択・抽出系
  - compensation: 補完・推定系
  - switching: 切替・代替系
  - normalization: 正規化・補正系
- B_terms: 制約・効果用語
- S_context: 技術的文脈（1-3段落、用途語を含めない）

【出力形式】
JSON形式で出力
```

## 4. HyDE summary生成

### 概要

Phase2 semantic laneのクエリとして、HyDE summaryを生成します。

### 入力

```python
S_context: str            # Phase1で抽出した技術的文脈
A_terms: List[str]        # コア技術用語
A_prime_terms: List[str]  # 対象・条件用語
```

### 処理

**LLM推論による自然言語サマリー生成:**
- S_contextをベースに
- A_terms, A_prime_termsを統合
- 1-3段落の自然言語パラグラフ
- **用途語（C_terms）は最小限に**

### 出力

```python
hyde_summary: str  # 自然言語パラグラフ
```

### LLMプロンプト例

```
以下の情報から、特許技術のサマリーを生成してください。

【技術的文脈】
{S_context}

【コア技術用語】
{A_terms}

【対象・条件用語】
{A_prime_terms}

【要件】
- 1-3段落の自然言語パラグラフ
- 技術的メカニズムに焦点
- 用途語（ゲート、入退室管理等）は最小限に
- キーワードリストではなく、文章として記述

【出力例】
顔認証技術において、カメラ映像から顔特徴を抽出し、登録データと照合することで個人を識別する。
マスク等により顔の一部が遮蔽されている場合、非遮蔽領域の特徴量を重み付けすることで認証精度を維持する。
プライバシー保護のため、特徴データの暗号化やローカル処理が求められる。
```

## 5. user_confirmation_protocol実装

### 概要

統一されたユーザ確認フォーマットで、各フェーズでの確認を実施します。

### 確認ポイント

**Phase0後: invention_interpretation**
```python
def confirm_invention_interpretation(feature_set: FeatureSet) -> str:
    """
    Generate invention interpretation confirmation
    """
    template = """
【発明の理解】
以下のように理解しました。

- コア技術（A）: {A_summary}
- 対象・条件（A'）: {A_prime_summary}
- 技術的手段（A''）: {A_double_prime_summary}
- 用途（C）: {C_summary}

【確認】
この理解で検索を進めてよろしいですか？

A: この理解で進める
B: コア技術の範囲を広げたい
C: コア技術の範囲を狭めたい
D: 用途（C）も必須条件として扱いたい

上記以外の修正があれば、自然文でお伝えください。
"""
    return template.format(
        A_summary=", ".join(feature_set.A_terms),
        A_prime_summary=", ".join(feature_set.A_prime_terms),
        A_double_prime_summary=", ".join(feature_set.A_double_prime_terms),
        C_summary=", ".join(feature_set.C_terms)
    )
```

**Phase1後: representative_review_confirmation**
```python
def confirm_representative_review(snippets: List[Snippet]) -> str:
    """
    Generate representative review confirmation
    """
    # Analyze snippets
    a_level_count = count_a_level_candidates(snippets)
    b_level_count = count_b_level_candidates(snippets)
    c_level_count = count_c_level_candidates(snippets)

    template = """
【代表公報レビュー結果】
上位{count}件のスニペットを確認しました。

- 技術的に近い文献: {a_level}件
- 部分的に関連: {b_level}件
- 関連薄い: {c_level}件

【確認】
Phase2（本検索）の方向性を選択してください。

A: このまま進める（現在のクエリ設計で本検索）
B: もう少し広げたい（recall重視に調整）
C: もう少し絞りたい（precision重視に調整）
D: 別の観点を追加したい

具体的な調整があれば、自然文でお伝えください。
"""
    return template.format(
        count=len(snippets),
        a_level=a_level_count,
        b_level=b_level_count,
        c_level=c_level_count
    )
```

**Phase2後: fusion_result_confirmation**
```python
def confirm_fusion_result(fusion_result: FusionResult, provenance: Provenance) -> str:
    """
    Generate fusion result confirmation
    """
    template = """
【検索結果サマリー】
融合後の上位候補: {total_count}件

- 技術分野分布: {top_fi_codes}
- 各レーンからの貢献: recall {recall_pct}%, precision {prec_pct}%, semantic {sem_pct}%
- 構造メトリクス: Fproxy {fproxy:.2f}, LAS {las:.2f}, CCW {ccw:.2f}

【確認】

A: 結果を確認する（上位30件のスニペット表示）
B: recallを上げたい（fulltext_recallの重みを増加）
C: precisionを上げたい（fulltext_precisionの重みを増加）
D: 検索をやり直したい（Phase1から再実行）

パラメータの具体的な調整があれば、自然文でお伝えください。
"""
    # Format top FI codes
    top_fi = sorted(provenance["code_freqs"]["fi"].items(), key=lambda x: x[1], reverse=True)[:3]
    top_fi_str = ", ".join([f"{code} ({count})" for code, count in top_fi])

    # Lane contributions
    lane_contrib = provenance["lane_contributions"]

    return template.format(
        total_count=len(fusion_result.ranked_docs),
        top_fi_codes=top_fi_str,
        recall_pct=int(lane_contrib.get("recall", 0) * 100),
        prec_pct=int(lane_contrib.get("precision", 0) * 100),
        sem_pct=int(lane_contrib.get("semantic", 0) * 100),
        fproxy=fusion_result.metrics.Fproxy,
        las=fusion_result.metrics.LAS,
        ccw=fusion_result.metrics.CCW
    )
```

## まとめ

LLMエージェント側コンポーネントの要点:

**feature_extraction:**
- LLM推論でA/A'/A''/B/C抽出
- synonym_cluster（core）構築

**code_profiling:**
- get_provenanceでコード頻度取得
- target_profile構築

**vocabulary_feedback:**
- peek_snippetsで代表公報取得
- LLM推論で語彙抽出（primary/extended）
- synonym_cluster更新
- Phase2クエリ再構築

**HyDE summary:**
- S_context + A_terms + A_primeから自然言語サマリー生成

**user_confirmation_protocol:**
- 統一フォーマットで確認
- invention_interpretation, representative_review, fusion_result

次章では、デプロイとメンテナンスを学びます。
