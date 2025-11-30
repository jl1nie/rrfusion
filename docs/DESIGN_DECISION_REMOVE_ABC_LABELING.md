# 設計判断: A/B/C ラベリングの完全削除

## 提案

Phase1 の代表特許レビュー（A/B/C ラベリング）を完全に削除し、最初の `target_profile` + `facet_terms` だけで融合を行う。

## 現在の Phase1 ワークフロー

```
1. feature_extraction (A/A'/A''/B/C 要素抽出)
2. code_profiling (FI/FT候補生成)
3. [ユーザ確認] → target_profile + facet_terms 決定
4. rrf_blend_frontier(target_profile, facet_terms) → 初回融合
5. peek_snippets(top 20) → レビュー
6. [ユーザ確認] → A/B/C ラベル決定
7. register_representatives(A/B/C) → 登録
8. rrf_mutate_run(facet_terms強化) → 再融合
```

## 提案する Phase1 ワークフロー

```
1. feature_extraction (A/A'/A''/B/C 要素抽出)
2. code_profiling (FI/FT候補生成)
3. [ユーザ確認] → target_profile + facet_terms 決定
4. rrf_blend_frontier(target_profile, facet_terms) → 融合（完了）
5. peek_snippets(適切な k) → 結果確認
```

---

## Pros/Cons 比較

### A/B/C ラベリングを削除する場合

#### ✅ Pros

##### 1. ワークフロー大幅簡素化
- **現在**: 8ステップ（ユーザ確認2回）
- **提案**: 5ステップ（ユーザ確認1回）
- LLM 実装負担が大幅に軽減
- ユーザの認知負担も軽減

##### 2. 「二度決め」の矛盾解消
現在のワークフローでは：
- Step 3 で `facet_terms` を決定（A/B/C 要素を定義）
- Step 6 で再度 A/B/C を決定（上位20件にラベル付け）

**問題点**:
- Step 3 で既に「どういう特許が A/B/C か」を定義済み
- Step 6 での再ラベリングは、Step 3 の定義と矛盾する可能性
- ユーザが「なぜ2回決めるのか？」と混乱

##### 3. facet_terms だけで十分
`facet_terms` で既に以下を定義している：
```yaml
A_terms: ["特徴抽出", "特徴量"]        # A要素（コア技術）
B_terms: ["重み付け", "補完"]          # B要素（解決手段の多様性）
C_terms: ["マスク", "遮蔽物"]          # C要素（課題の多様性）
```

これに基づいて融合すれば、わざわざ20件をレビューして再分類する必要なし。

##### 4. 主観的判断の排除
- 20件レビューでの A/B/C 判定は主観的
- サーチャーごとに判断が分かれる可能性
- `facet_terms` による機械的な分類の方が一貫性が高い

##### 5. 計算効率向上
- 再融合（mutate_run）が不要
- Redis への往復通信が減る
- 処理時間短縮

##### 6. コード削減
- `register_representatives` ツール削除
- `RepresentativeEntry` モデル削除
- facet boosting ロジック簡素化
- テストコード削減

---

#### ❌ Cons

##### 1. フィードバックループの喪失
**現在の設計意図**:
- 初回融合結果（top 20）を見て、`facet_terms` の妥当性を検証
- ズレがあれば `facet_terms` を調整して再融合

**削除すると**:
- 一発勝負になる
- `facet_terms` が不適切でも気づきにくい

**反論**:
- ユーザは peek_snippets で結果を確認できる
- 不満があれば新しい fusion run を作成すればよい
- 実際には `facet_terms` 調整は稀（ほとんどのケースで初回で十分）

##### 2. 柔軟性の低下
**現在の設計**:
- 上位20件を見て、予想外に良い特許が混ざっていた場合に調整可能
- 「この特許は B だと思ったけど実際は A だった」のような発見に対応

**削除すると**:
- そのような調整ができなくなる

**反論**:
- Phase1 は「代表特許探索」であり、完璧な分類は求めない
- Phase2 で最終的な Batch Retrieval を行うので、Phase1 は方向性が合えば十分

##### 3. 代表特許という概念の消失
**現在の設計**:
- A/B/C ラベル付き代表特許が明示的に記録される
- これを Phase2 に引き継ぐ

**削除すると**:
- 「代表特許」という明確なマーカーがなくなる
- Phase2 は何を基準に Batch Retrieval するのか？

**反論**:
- Phase1 の `target_profile` + `facet_terms` が Phase2 の基準になる
- 代表特許を明示的に保存する必要はない

##### 4. facet boosting の効果が不明確
**現在の設計**:
- A/B/C ラベル付き代表特許に基づいて facet score を計算
- π(d) に組み込んで frontier 計算

**削除すると**:
- facet_terms だけで boosting できるのか？
- 実装がより複雑になる可能性

**反論**:
- `facet_terms` ベースの boosting は既に実装されている（`compute_pi_scores`）
- 代表特許なしでも動作する

---

## 技術的実装への影響

### 削除する必要があるもの

1. **MCP ツール**
   - `register_representatives`

2. **Pydantic モデル**
   - `RepresentativeEntry`
   - `BlendRequest.representatives` フィールド

3. **Fusion ロジック**
   - `compute_pi_scores` の代表特許ブースト部分
   - `_normalize_representatives` メソッド

4. **SystemPrompt**
   - `user_confirmation_protocol` の representative review セクション
   - `register_representatives` ツール説明

5. **テスト**
   - `test_register_representatives`
   - representative 関連の統合テスト

### 変更が必要なもの

1. **`compute_pi_scores`**
   - 現在: 代表特許の A/B/C ラベルに基づいて facet score 計算
   - 変更後: `facet_terms` だけで計算

2. **Phase1 ワークフロー**
   - SystemPrompt から representative review ステップ削除
   - ユーザ確認を1回に統合

3. **Phase2 引き継ぎ**
   - 現在: 代表特許を recipe に保存
   - 変更後: `target_profile` + `facet_terms` だけを保存

---

## facet_terms だけで十分な理由

### 現在の facet boosting の仕組み

```python
def compute_pi_scores(
    doc_metadata: dict[str, dict],
    target_profile: dict[str, dict[str, float]],
    facet_terms: dict[str, list[str]],  # A/B/C_terms
    facet_weights: dict[str, float],    # A/B/C の重み
    lane_ranks: dict[str, dict[str, int]],
    lane_weights: dict[str, float],
    pi_weights: dict[str, float],
) -> dict[str, float]:
    # 各文献について:
    # 1. code score (target_profile に基づく)
    # 2. facet score (facet_terms に基づく)
    # 3. lane score (lane_ranks に基づく)
    # π(d) = code * w_code + facet * w_facet + lane * w_lane
```

**facet score の計算**:
- 文献の title/abst/claim に `facet_terms` の用語が出現するか判定
- A_terms に一致 → A score
- B_terms に一致 → B score
- C_terms に一致 → C score
- 重み付け合計して返す

**代表特許を使う場合**:
- 20件のうち doc X が「A ラベル」なら、X と似た文献に A boost
- 似ているかどうかは... どう判定？ → 実装が曖昧

**結論**: `facet_terms` ベースの方が明確で再現性が高い

---

## ユースケース別評価

### ケース1: 典型的な Phase1 実行

**現在**:
```
1. 発明開示書を読む
2. A/A'/A''/B/C 要素を抽出 → facet_terms 決定
3. FI/FT を選定 → target_profile 決定
4. 融合 → top 20 レビュー
5. 「やっぱりこの特許は A じゃなくて B だ」と判断
6. register_representatives
7. 再融合
```

**提案**:
```
1. 発明開示書を読む
2. A/A'/A''/B/C 要素を抽出 → facet_terms 決定
3. FI/FT を選定 → target_profile 決定
4. 融合 → 完了
5. peek で結果確認
```

**評価**: 提案の方が明らかにシンプル。Step 5 の再判断は実際にはほとんど発生しない。

---

### ケース2: facet_terms が不適切だった場合

**現在**:
```
1. 融合 → top 20 が期待と異なる
2. A/B/C ラベルを再調整
3. 再融合
```

**提案**:
```
1. 融合 → peek で確認
2. facet_terms を修正
3. 新しい fusion run を作成
```

**評価**: ほぼ同等。再融合 vs 新規作成の違いだけ。

---

### ケース3: Phase2 への引き継ぎ

**現在**:
- 代表特許 (A/B/C ラベル付き) を recipe に保存
- Phase2 で同じ facet boosting を適用

**提案**:
- `target_profile` + `facet_terms` を recipe に保存
- Phase2 で同じ基準を適用

**評価**: ほぼ同等。むしろ提案の方がシンプル。

---

## 推奨案

### Option A: A/B/C ラベリング完全削除（強く推奨）

**理由**:
1. ワークフロー大幅簡素化（8→5ステップ）
2. 「二度決め」の矛盾解消
3. `facet_terms` だけで十分な精度
4. 実装・保守コストの削減
5. ユーザの認知負担軽減

**移行方針**:
1. `register_representatives` ツールを deprecated にマーク
2. SystemPrompt から representative review ステップ削除
3. `compute_pi_scores` を facet_terms ベースのみに簡素化
4. テスト更新・ドキュメント更新
5. 次期バージョンで `register_representatives` 削除

**Breaking Change 対策**:
- 既存の recipe に `representatives` が含まれていても無視（エラーにしない）
- `register_representatives` 呼び出しは成功させるが、何もせず warning ログ

---

### Option B: 現状維持

**理由**:
1. フィードバックループが理論的には有用
2. 柔軟性の保持
3. 既存実装の活用

**改善方針**:
1. SystemPrompt で representative review の意義を明確化
2. ユーザに「スキップ可能」と説明
3. デフォルトでは省略、必要な場合のみ実行

---

## 結論

**推奨: Option A (A/B/C ラベリング完全削除)**

理由:
- **実用性**: 実際のワークフローで representative review は冗長
- **一貫性**: Step 3 の facet_terms と Step 6 の A/B/C が二重管理
- **簡潔性**: ツール数・実装量・ユーザ負担すべてが削減
- **有効性**: facet_terms だけで十分な精度が得られる

**唯一のデメリット（フィードバックループ喪失）への対策**:
- peek_snippets で結果確認可能
- 不満があれば facet_terms 修正 → 新規 fusion run 作成
- Phase1 は「方向性確認」なので完璧を求めない

---

**作成日**: 2025-11-30
**ラベル**: `design-decision`, `workflow-simplification`, `phase1-optimization`
