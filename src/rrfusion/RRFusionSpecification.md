# RRFusion MCP v1.3 開発者向けドキュメント（専門版）

**対象読者ペルソナ**

- 特許検索の実務経験あり（無効資料調査、新規性・進歩性、FTO 等を日常的に実施）
- IT・プログラミングは専門ではないが、  
  - ロジックやフロー図は理解できる  
  - 数式は、説明があれば読み解けるレベル（理系大学院卒程度）

**この文書を読むとできるようになること**

- RRFusion MCP が「内部で何をしているのか」を構造的に説明できる
- レーン設計（`fulltext_wide` / `semantic` / `fulltext_recall` / `fulltext_precision`）の意味と役割を理解し、修正できる
- コード体系（FI/FT/CPC/IPC）の扱いと、なぜ混在が禁止されるかを説明できる
- 検索性能に問題があるときに、どこを調整するかの見当をつけられる
- 将来の改良（新レーン追加、β調整、クエリ設計の変更）を、実務の観点から検討・指示できる
- MCPツールAPI仕様を見て、LLMエージェントやバックエンド実装者と具体的な会話ができる

---

## 0. 全体像と設計哲学

### 0.1 何を解決しようとしているか

特許検索は、以下のような困難を常に抱えています。

1. **用語の揺れ（シノニム・パラフレーズ）**
   - 「光放射素子」と「発光素子」
   - 「供給」と「供給手段」と「給電」
   - 同じ概念が多様な表現で書かれる

2. **構成要素の組み合わせ**
   - A, B, C の三つの特徴が揃って初めて「本件発明らしい」文献になる
   - しかし検索式では AND/OR の組み合わせが爆発しやすい

3. **技術分野の境界**
   - 似た用語が全く別分野で使われる（例：通信と医用機器）
   - 分類コード（FI/FT/CPC/IPC）の助けは有用だが、設計を誤ると絞りすぎ・広げすぎになる

4. **評価用の「正解データ」がない**
   - 多くの実務では「正解リスト」が存在せず、F値（Fβ）を厳密に計測できない
   - それでも「一般に見て良い検索」になっているかは判断しなければならない

RRFusion MCP は、これらの困難に対して、

- **複数のレーン（検索パターン）を並列に試す**
- それらの結果を **RRF（Reciprocal Rank Fusion）とコードプロファイル** で統合する
- 明示的な「正解ラベル」がなくても、**Fβ を最大化するような設定を探索しやすくする**

というアプローチをとるコンポーネントです。

### 0.2 RRFusion MCP の役割

RRFusion MCP 自体は、**検索エンジン（OpenSearch 等）のフロントに立つ「メタ検索エンジン」** として設計されています。

- バックエンド：
  - FI/FT/CPC/IPC、請求項/要約/明細書などを保持した特許 DB
  - fulltext（TT-IDF/BM25 系）、semantic（ベクトル）といった検索 API を提供
- RRFusion MCP：
  - 「どのレーンにどんなクエリを投げるか」を決める
  - レーンごとの結果（run_id）を受け取り、RRF + コードプロファイルで融合する
  - スニペット抽出やフロンティア評価など、実務で必要な「周辺ロジック」を提供

さらに、その上に **LLM エージェント** が載ることを前提としています。

- LLM（エージェント）：
  - ユーザからの自然文の質問を解釈
  - 特徴語の抽出・シノニム生成
  - どのレーンにどのようなクエリを投げるかを設計
  - 結果（ランク・スニペット）をユーザに説明しやすい形に整形

### 0.3 設計哲学（Design Principles）

RRFusion MCP v1.3 では、次のような設計哲学を重視しています。

1. **レーンの独立性**
   - 各レーンは「ある思想に基づく検索式のテンプレート」として定義される
   - レーン内のクエリ設計は LLM で柔軟に変えられるが、レーンの役割（wide / recall / precision / semantic）は固定する

2. **観測可能性（Observability）**
   - どの文献がどのレーンから来たのか
   - コード的にどの分野に属しているか
   - あるチューニングが precision / recall にどう効いていそうか  
   を、人間が「数値」と「スニペット」で把握できるようにする

3. **安全なデフォルト**
   - v1.3 のデフォルト設定は、「少なくとも大外しはしにくい」ように設計
   - 高度なチューニング（β調整、レーン追加）は後から段階的に導入できる

4. **手動チューニングと自動チューニングの両立**
   - 実務家が「もう少しこの分野を厚く」「このコードは弱く」といった指示を出せる余地を残す
   - 一方で、`mutate_run` などを通じてパラメータ探索を半自動化できる

---

## 1. 数理的な基礎：BM25 / ベクトル類似度 / RRF / Fβ

ここでは、RRFusion MCP の中核となる数式を整理します。  
理解が曖昧でも運用はできますが、「なぜそのような挙動をするか」の直感が得られるため、一度目を通しておくことを推奨します。

### 1.1 Lexical 検索（BM25 / TT-IDF のイメージ）

TT-IDF は BM25 と同系統のスコアリングです。BM25 の代表的な式は次の通りです（概念レベル）：

\[
\text{BM25}(d, q) = \sum_{t \in q} \text{IDF}(t) \cdot 
\frac{f(t, d) \cdot (k_1 + 1)}{f(t, d) + k_1 \cdot \left(1 - b + b \cdot \frac{|d|}{\text{avgdl}}\right)}
\]

- $d$：文書
- $q$：クエリ
- $t$：クエリ中の用語（term）
- $f(t, d)$：文書 $d$ における用語 $t$ の出現頻度
- $ |d| $：文書長
- avgdl：平均文書長
- $k_1, b$：調整パラメータ

**ポイント**

- 用語が多く出るほどスコア上昇
- 文書長が長すぎると評価が補正される
- IDF（逆文書頻度）により「よく出る一般語」は弱く、「珍しい専門語」は強く評価される

RRFusion MCP では、具体的な式は検索バックエンドに依存しますが、  
「TT-IDF/BM25 に似た性質の lexical スコアを返す検索」と考えれば十分です。

### 1.2 Dense 検索（ベクトル類似度）

Dense 検索は、文書やクエリをベクトル（埋め込み）に変換し、その類似度でランキングするものです。

- クエリ $q$ と文書 $d$ をそれぞれベクトル $v_q, v_d$ に写像
- 類似度（スコア）をコサイン類似度などで定義

\[
\text{sim}(q, d) = \frac{v_q \cdot v_d}{\|v_q\| \cdot \|v_d\|}
\]

- 「言い換え」や「関連する概念」を拾いやすい
- 一方で、**細かい構成要素の一致**や「否定・限定（〜以外）」などの扱いは苦手なことが多い

RRFusion MCP では、レーン `semantic` や将来実装予定の `original_dense` がこの役割を担います。

### 1.3 RRF（Reciprocal Rank Fusion）

複数のレーンから得られたランキング結果を統合するために、RRF（Reciprocal Rank Fusion）を用います。  
基本形は次の通りです。

\[
\text{RRF}(d) = \sum_{\ell} \frac{1}{k + \text{rank}_\ell(d)}
\]

- $\ell$：レーン（`fulltext_wide`, `semantic`, `fulltext_recall`, `fulltext_precision`, ...）
- $\text{rank}_\ell(d)$：レーン $\ell$ における文献 $d$ の順位（1始まり）
- $k$：調整パラメータ（ランキングが「効きすぎる」のを和らげる役割）

RRFusion MCP では、レーンごとに重み $w_\ell$ を掛けた形で使います。

\[
\text{RRF}_w(d) = \sum_{\ell} w_\ell \cdot \frac{1}{k + \text{rank}_\ell(d)}
\]

これにより、

- wide レーンは「見落とし防止のために広く拾うが、重みは控えめ」
- precision レーンは「上位に来たものを強く押し上げる」
- semantic レーンは「lexical に拾いきれない関連文献を補完する」

といった設計が可能になります。

### 1.4 Precision / Recall / Fβ（概念レベル）

RRFusion MCP v1.3 は、実務上の制約から「厳密なラベル付きデータ」を前提としていませんが、  
設計思想としては F値（特に Fβ）を意識しています。

- Precision（適合率）：  
  - 上位に出てきた文献のうち、「本当に関連がある」ものの割合
- Recall（再現率）：  
  - 「本当に関連がある」文献のうち、検索で拾えている割合
- F値（Fβ）：  
  - Precision と Recall の調和平均（β は Recall をどれだけ重視するかを表す）

\[
F_\beta = (1 + \beta^2) \cdot \frac{\text{Precision} \cdot \text{Recall}}{(\beta^2 \cdot \text{Precision}) + \text{Recall}}
\]

- $\beta > 1$：Recall 重視（見落としを嫌う）
- $\beta < 1$：Precision 重視（外れ文献を嫌う）

実際には「真の Precision / Recall」はわかりませんが、

- コード分布（target_profile との一致度）
- スコア分布（上位と下位の差）
- スニペットの内容（人間の目によるジャッジ）

などを proxy として、Fβ が高くなりそうな設定を **探索・固定する** という思想で設計されています。

---

## 2. コード体系と target_profile

ここでは、FI/FT/CPC/IPC といった分類コードの扱いと、  
RRFusion MCP で導入している `target_profile` の概念を整理します。

### 2.1 コード体系の種類

> この文書では、`FT`（F-term）分類を言及するときは一貫して `F-term` と表記し、`FT` は括弧内の略称としてのみ用いるようにします。混乱を避けるため、以後 `F-term` と呼ぶときは必ずこの語を使ってください。

特許検索でよく使うコード体系は、主に次の 4 つです。

1. **FI（File Index, 日本独自の詳細分類）**
   - JPO（日本特許庁）が運用する細分類
   - IPC を基礎に、より細かい階層を持つ
   - 日本語実務では最も馴染みが深い

2. **FT（F-Term, 特許分類テーマごとのタグ）**
   - 技術テーマごとに設計されたタグセット
   - FI と組み合わせて使うことで、構成要素や用途などを表現しやすい

3. **CPC（Cooperative Patent Classification）**
   - EPO / USPTO 共同の詳細分類
   - 欧米系文献で広く採用されている
   - IPC より細かい

4. **IPC（International Patent Classification）**
   - 国際的な基本分類
   - 粒度はやや粗いが、世界中の文献に付与されている

それぞれ設計思想・粒度・運用の歴史が異なり、  
**「どの体系を主とするか」** によって、検索結果の傾向も大きく変わります。

### 2.2 レーンごとにコード体系を混在させてはいけない理由

v1.3 では **「1つのレーンの中で、異なるコード体系を混ぜてはいけない」** というルールがあります。

禁止例：

- FI + CPC
- FI + IPC
- FT + CPC
- CPC + IPC

理由：

1. コード体系ごとに設計思想・粒度が異なるため
   - FI は非常に細かいが、日本系文献中心
   - CPC は欧米系文献に強く、IPC より細かい
   - IPC は粗いが、世界中に広く付いている
2. これらを同一レーンで混在させると、「どの粒度で絞り込んでいるのか」が不明瞭になる
3. RRFusion MCP 側でコード分布を解析するときに、  
   「FI のこのコードと CPC のこのコードはどちらがどの程度強いのか」といった比較が難しくなる

したがって、

- **レーンごとに「このレーンは FI/FT だけ」「このレーンは CPC だけ」というように役割を固定する**
- JP 系文献が標準の場合は FI を主体系とし、必要に応じて補助的に F-Term を加える（構造/用途などの補足に限定）。JP以外のターゲットで CPC/IPC を使う場合には、その文脈の全レーンで CPC/IPC を統一して、クエリ・セマンティック記述も英語で構築すること。
- 後段でコード分布を見て target_profile を作るときも、「同じ体系どうし」で比較する

というポリシーを採用しています。

### 2.3 RRFusion MCP v1.3 のコード運用ルール

- JP 系文献：
  - **FI を主体系**
  - 必要に応じて FT を補助的に使う
- US/EP/WO 系文献：
  - **CPC または IPC のどちらか一方**

特定レーンでは、**必ず一つの体系だけ**を使うこと。  
（例：`fulltext_recall` では FI/FT のみ、`fulltext_precision` でも同じく FI/FT のみ、というように整合を保つ）

---

## 3. レーン設計の詳細

この章では、RRFusion MCP v1.3 で前提としているレーン構成と、それぞれの役割・想定クエリ・フィールド設計を整理します。

- `fulltext_wide` レーン
- `semantic` レーン
- `fulltext_recall` レーン
- `fulltext_precision` レーン
- （オプション）コード専用レーン

レーンごとの違いは **「クエリ設計」＋「フィールド・コード制約」＋「RRF 重み付け」** にあり、基盤となる検索ツールは次のように対応します。

- `fulltext_*` 系：`search_fulltext`
- `semantic`：`search_semantic(semantic_style="default" | "original_dense")`
  - v1.3 現在、`semantic_style="original_dense"` 経路は **実行時には disabled** であり、実運用では常に `"default"` を使用する
- コード専用レーン：RRFusion MCP 内部で組み立てたコードスコア ZSET を利用

> **補足：** 本書で `fulltext_wide` / `fulltext_recall` / `fulltext_precision` のように呼んでいるのは「LLM や人間が意味する論理レーン」であり、FastMCP に渡す実際のリクエストは物理レーン（主に `fulltext` / `semantic` / `original_dense`）に番号を同じにして投げていきます。論理レーンごとの役割やフィルタ制約は `BlendRunInput` や `run metadata` で補足し、`search_fulltext` の結果ハンドルを `fulltext_wide` の代表とみなして fusion に渡す仕組みになっています。

### 3.1 レーン一覧とざっくりした役割

| レーン名              | 主ツール                                   | 目的                             | 典型的なクエリの長さ      | コード制約               | 主な MCP パラメータ                                       |
|----------------------|--------------------------------------------|----------------------------------|---------------------------|--------------------------|------------------------------------------------------------|
| `fulltext_wide`      | `search_fulltext`                          | 落とし穴防止のための「広い網」  | 長め（数百〜千文字程度）  | 原則なし（ゆるめ）       | `field_boosts` は title 強め・desc 弱め（デフォルト）     |
| `semantic`           | `search_semantic(semantic_style="default")`| 概念的に近い文献の補完          | 中程度（〜1024 文字目安）| レーンごとに統一         | `feature_scope="wide"` を基準に、場合により絞り込む       |
| `fulltext_recall`    | `search_fulltext`                          | ターゲット分野を厚く拾う        | 中程度（特徴語中心）      | FI/FT or CPC/IPC のどれか| `field_boosts` で desc/claim をやや厚めにする             |
| `fulltext_precision` | `search_fulltext`                          | 「本命候補」の絞り込み           | 短め（特徴語＋構成要素）  | `fulltext_recall` と同一 | `field_boosts` で title/claim を強く、desc は弱く         |
| code-only（任意）    | 内部 ZSET                                  | コード的ど真ん中の軽い押し上げ  | なし                      | 体系固定                 | `BlendRequest.target_profile` / コードレーン用 `weights`  |

以降、各レーンの詳細と、「どのように MCP パラメータを変えることで新レーンを増やせるか」を説明します。

---

### 3.2 fulltext 系レーンと `field_boosts` の設計

fulltext 系レーンは、同じ `search_fulltext` を使いながら  
`field_boosts`（タイトル／要約／クレーム／明細書などの重み）を変えることで役割を分けます。

#### 3.2.1 代表的な `field_boosts` の例

実装レベルでは Patentfield の `weights` にマッピングされますが、  
論理レーンの観点では次のようなプリセットとして扱うと整理しやすくなります。

| 論理レーン           | 役割                         | 典型的な `field_boosts`（概念）                                      |
|----------------------|------------------------------|------------------------------------------------------------------------|
| `fulltext_wide`      | 分野の当たりをつける        | `{"title": 80, "abstract": 10, "claim": 5, "description": 1}`         |
| `fulltext_recall`    | 分野内の coverage を厚くする | `{"title": 40, "abstract": 10, "claim": 5, "description": 4}`         |
| `fulltext_precision` | 本命候補の絞り込み           | `{"title": 120, "abstract": 20, "claim": 40, "description": 1}`       |

- `fulltext_wide`  
  - タイトルを強めに、明細書は弱めにして「方向性が近い文献」を広く拾う。
- `fulltext_recall`  
  - 明細書もある程度見ることで、「同じコード帯の近い技術」を漏らしにくくする。
- `fulltext_precision`  
  - タイトル／クレームをかなり強くし、「発明の骨格が似ている文献」を優先する。

LLM や実務者が新レーンを設計する場合は、  
この表を基準に `field_boosts` を少しずつ変えながら `blend_frontier_codeaware` → `peek_snippets` で結果を比較し、  
「wide / recall / precision の中間」などのレーンを追加していくことができます。

---

### 3.3 semantic レーンと `feature_scope` のバリエーション

semantic レーンは、バックエンドの `score_type="similarity_score"` を用いた類似度検索ですが、  
`feature_scope` によって「どのセクションから特徴量を抽出するか」を切り替えられます。

| semantic 論理レーン         | `feature_scope`         | Patentfield `feature` への対応       | 主な用途                                   |
|-----------------------------|-------------------------|--------------------------------------|--------------------------------------------|
| `semantic_wide`             | `"wide"`                | `word_weights`                       | 最初に広く関連文献を拾う                   |
| `semantic_title_abst_claim` | `"title_abst_claims"`   | `claims_weights`                     | タイトル＋要約＋クレームの雰囲気を見る     |
| `semantic_claims_only`      | `"claims_only"`         | `all_claims_weights`                 | クレーム構成が似た文献にフォーカス         |
| `semantic_top_claim`        | `"top_claim"`           | `top_claim_weights`                  | クレーム 1 本目同士の比較                  |
| `semantic_background_jp`    | `"background_jp"`       | `tbpes_weights` 系                   | JP の背景技術／課題／効果の雰囲気を把握    |

- デフォルトは `feature_scope="wide"` とし、「semantic はまずは広く」という立ち位置。
- 特定の比較（例：クレーム構成の近さ）に絞りたい場合は、`semantic_claims_only` のような論理レーンを定義して使います。
- 将来的に dense ベクトル検索（`original_dense`）を導入するときは、  
  ここでの semantic は「Patentfield similarity 専用」、dense は別レーンとして棲み分ける想定です。

---

### 3.4 新しい論理レーンを追加する手順

RRFusion MCP では、**MCP ツールを増やさなくても** 新しい論理レーンを増やすことができます。  
設計の観点からは、次の 4 ステップで整理すると分かりやすくなります。

1. **物理レーンを選ぶ**  
   - lexical を厚くしたい：`search_fulltext`  
   - 類似度（Patentfield similarity）で補完したい：`search_semantic`  
2. **テキストのフォーカスを決める**  
   - fulltext：`field_boosts`（title/abstract/claim/desc の比重）  
   - semantic：`feature_scope`（wide / claims_only / background_jp など）
3. **コード・フィルタを決める**  
   - FI/FT/CPC/IPC、出版年、国、言語などを `filters: list[Cond]` として固定する。
4. **fusion 上の役割を決める**  
   - `BlendRequest.weights` で wide/recall/precision のどれに近いかを調整し、  
     必要に応じて `beta_fuse` や `target_profile` を設定する。

例：

- `semantic_claims_strict` レーン  
  - `search_semantic` + `feature_scope="claims_only"`、FI/FT を絞り込んだフィルタ、fusion では precision 寄りの weight を付与。
- `fulltext_background_wide` レーン  
  - `search_fulltext` + desc や background に少し厚めの `field_boosts` を設定し、分野の広い当たりを付ける用途に使う。

このように、「論理レーン = 物理レーン + MCP パラメータプリセット」と捉えることで、  
将来的なレーン追加や調整を、MCP ツールの枠組みの中で安全に拡張していくことができます。

---

### 3.1.1 検索式（`query`）の構文ルールと A/B/C 分解の基本方針

バックエンドの fulltext 検索に渡す `query` は、以下の部品で構成される検索式です。

- キーワード（1語以上）
- 論理演算子
- 括弧によるグルーピング
- 特殊キーワード（フレーズ検索・近傍検索）

#### 論理演算子

- 論理積：`AND` / `and` / 指定なし（省略時は AND とみなす）
- 論理和：`OR`
- 論理否定：`NOT` / `not`

例：

- `solar AND panel`
- `solar OR panel`
- `solar NOT panel`

#### グルーピング

- 丸括弧 `()` でグルーピングできる。
- 例：`(solar OR ソーラー) AND パネル`

#### フレーズ検索

- ダブルクォーテーション `"` で囲むと、その順序・連続で出現するフレーズとして検索する。
- 例：`"solar panel"`  
  `"solar panel"` という文字列が連続して出現する文書だけをヒットさせる。

#### 近傍検索（NEAR）

複数キーワード間の距離（文字数）を指定して検索する。

- 形式：`*N5"太陽 電池"` のように、`*`＋コマンド＋距離＋`"語1 語2 ..."` を指定する。
- 括弧 `()` を用いて、候補語の集合を指定できる。
- 近傍検索の内部では、入れ子の括弧や AND/OR/NOT はサポートしない。

コマンドの種類：

- `N`：順不同の近傍検索
- `NP`：順不同の近傍検索（挙動は `N` と同じ）
  - 例：`*N5"太陽 電池"`  
    「太陽」から「電池」または「電池」から「太陽」までの距離が 5 文字以内の文章を検索。
- `ONP`：指定順近傍検索（語順を固定）
  - 例：`*ONP5"太陽 電池"`  
    「太陽」から「電池」までの距離が 5 文字以内の文章を検索（「電池」の後に「太陽」が 5 文字以内に現れてもヒットしない）。

括弧で候補を束ねた例：

- `*N10"(太陽 ソーラー) (電池 パネル)"`  
  「太陽 と 電池」「太陽 と パネル」「ソーラー と 電池」「ソーラー と パネル」のいずれかが 10 文字以内に出現する文章を検索。

LLM が search_fulltext の `query` を組み立てる際は、上記の構文ルールに従って「自然文＋構成要素＋必要なときの近傍検索」を組み合わせる。

あわせて、feature_extraction ではユーザの説明から出てくる情報を少なくとも次の 3 カテゴリに分けておくと、その後のレーン設計が安定します。

- **コア技術 (Core technical mechanism)**  
  - 顔認証アルゴリズム、冷却構造、センサ構成、制御ロジックなど、「発明の骨格」をなす技術要素。
- **制約・副次的条件 (Constraints / secondary conditions)**  
  - レイテンシ、コスト、安全性、プライバシーといった、コア技術に付随する条件や評価軸。
- **用途・シーン (Use cases / deployment contexts)**  
  - ゲート、入退室管理、車載、医療機器など、「どこで使うか」を示す文脈。

v1.3 では、wide や in-field レーンのクエリ設計において:

- コア技術は A/B 側（必須〜重要構成）として扱い、
- 用途・シーンは C 側（用途・導入シーン）の要素として扱う

ことを原則とします。特に `fulltext_wide` では、ゲート／入退室／車載など **用途側の語を AND/MUST に入れず、SHOULD（OR）グループに留める** ことで、「用途は違うが技術コアが同じ」先行技術を early-stage で取りこぼさないようにするのが重要です。

---

### 3.2 `fulltext_wide` レーン

**目的**

- 「この問題設定で、そもそもどのあたりの分野が絡んできそうか」を俯瞰するための、**最も広いレーン**。
- 上位 100〜300 件程度の「顔ぶれ」を作ることが主目的で、  
  ここからコード分布を観測し `target_profile` を構築します。

**クエリの特徴**

- ユーザの自然文説明から主要な技術要素を抽出し、必ず **キーワード／Boolean 検索式としての `query`** に変換してから `search_fulltext` を呼び出す。
- 検索式は、技術用語・（必要に応じて）分類コード・論理演算子（AND/OR/NOT）、フレーズ（"`...`"）、近傍検索（`*N5"..."` など）を組み合わせて構成し、自然文の段落をそのまま渡さない。
- wide レーンでは AND ブロックは 2〜3 個程度に抑え、NOT 条件はユーザが明示的に「除外してほしい」と指定した場合に限定する。過剰な AND/NOT による絞り込みは避け、あくまで「広く当たりをつける」役割を意識する。
- クエリ長の目安：
  - 実装上はおおむね 〜256 文字程度を目安とし、それを超える場合は重要な語に絞り込む（バックエンド側の制約に従いつつ、必要に応じて調整してよい）。

**フィールド設計**

- タイトル、要約、請求項、明細書の主要部分を広く対象とする。
- バックエンド側の典型的な設定例：
  - title, abstract, claims, description に対して均等〜やや claims 重み寄り
- レーンレベルの filters ではコード体系（FI/FT/CPC/IPC）によるハードな絞り込みは原則つけない（`code_system_policy.allow: none` に相当し、技術分野の先入観による取りこぼしを避ける）。  
  一方で、検索式中に FI/FT などの分類コードをキーワードとして含めることはあり得るが、その場合でも wide レーンでは「分野のおおまかな当たりをつける」用途に留め、過度に狭いコードで締め付けない。

**コード分布と target_profile**

- `fulltext_wide` から得られた run（例：`run_id_fulltext_wide`）に対して `get_provenance` を 1 回呼び出し、
  - FI/FT/CPC/IPC コードの頻度分布を観測する。
- その分布をもとに、LLM 側ロジックで `target_profile` を作る：
  - 頻度が高く、かつ特異度が高いコードを抽出
  - 上位 n 個（例：10〜30 個）を採用
  - 適切に正規化して「重み付き辞書」とする

---

### 3.3 `semantic` レーン

**目的**

- 自然文レベルでの「概念的な近さ」を補完するレーン。
- lexical な完全一致に依存せず、関連する言い換え・周辺概念の文献を拾う役割。

**`search_semantic` と `semantic_style`**

`search_semantic` は、引数 `semantic_style` によって内部の実装を切り替えられる設計になっています。

- 型：`semantic_style: Literal["default", "original_dense"]`
- デフォルト値：`"default"`  
  （`host.py` 側の定義：`semantic_style: SemanticStyle = "default"`）

意味合いは以下の通りです。

- `semantic_style="default"`  
  - LLM による要約・再構成を用いた **fulltext ベース** の semantic レーン  
  - 実体としては BM25 系の fulltext 検索を使いつつ、  
    クエリ側で概念的な表現に寄せることで semantic 的な挙動を得る
- `semantic_style="original_dense"`  
  - 将来実装予定の **ベクトル検索（original_dense）** を用いるモード
  - v1.3 現在、この経路は **実行時には disabled** であり、使用しないこと

したがって、v1.3 の LLM レシピでは：

- `search_semantic` を呼ぶ場合は、明示的に  
  `semantic_style: "default"` を指定するか、省略（＝ "default"）とする
- `"original_dense"` は予約語として残るが、v1.3 では選択してはならない

**クエリの特徴**

- LLM がユーザの説明から「本質的な技術課題・解決手段」を短く要約し、  
  それをクエリの中心に据える。
- 具体的な構成要素の列挙よりも、
  - 技術分野
  - 目的・効果
  - キーとなる動作や関係
  を重視した表現にする。
- クエリ長の目安：
  - 〜 1024 文字程度の短めテキスト
  - 1〜3 段落程度で「この発明の肝」をまとめるイメージ

**フィールド設計**

- claims＋abstract を中心に、title も加える形が多い。
- 明細書本体はあえて弱くするか、対象外にしてもよい（実装ポリシー次第）。

**コード制約**

- 必要に応じて `target_profile` を参照し、  
  「明らかに分野外のコードを持つ文献」をゆるく除外することも可能。
- ただし、`semantic` レーンでは過度にコードで絞らず、  
  あくまで「概念として近い候補を拾う」ことを優先する。

---

### 3.4 `fulltext_recall` レーン

**目的**

- `fulltext_wide` と `semantic` で把握した技術分野を踏まえ、  
  **ターゲット分野の文献を「厚く拾う」ためのレーン**。
- Recall を稼ぐ役割であり、多少のノイズ混入は許容する。

**クエリの特徴**

- LLM が抽出した特徴語・シノニム群を用い、
  - 技術分野（用途・構造・動作）
  - コアとなる構成要素
  を網羅的に OR/AND で組み立てる。
- `fulltext_wide` よりも構成要素を明示的に AND で結ぶが、
  - 各要素内では OR で複数シノニムを許容する。
- クエリ長の目安：
  - 特徴語＋シノニム群を中心に、中程度の長さ（数十〜数百トークン）。

**フィールド設計**

- claims＋abstract を中心に、description の関連部分も対象にする。
- precision レーンほど絞り込まないが、title だけに偏らないようにする。

**コード制約**

  - `fulltext_wide` から得た `target_profile` に基づき、
    - FI/FT または CPC/IPC のうち、**体系を一つに固定**してフィルタする（JP 系なら FI/FT、非JP 系なら CPC/IPC ）。JP 以外のレーンではクエリ・semantic 文書を英語にして体系とターゲットを明示する。
    - 例：JP 系中心なら FI/FT、US/EP/WO 中心なら CPC。
- 「target_profile に含まれるコード群」を SHOULD / FILTER として使い、  
  近い分野の文献を厚く拾う。

---

### 3.5 `fulltext_precision` レーン

**目的**

- `fulltext_recall` で得た分野の中から、  
  **「本命候補」を絞り込むレーン**。
- 高い Precision を狙うため、構成要素の組み合わせをより厳密に見る。

**クエリの特徴**

- 特徴語と構成要素を、LLM が「請求項のクレームチャート」を作るイメージで整理し、
  - A：必須構成要素
  - B：重要な限定要素
  - C：付加的な好適例
  などに分ける。
- クエリとしては、
  - A と B を AND 必須
  - C は SHOULD または省略可
  のような形で組み立てる。
- クエリ長の目安：
  - `fulltext_recall` より短く、キーとなるターム群に絞る。

**フィールド設計**

- claims を最重視しつつ、abstract と description も対象とする。
- abstract は補助的に見る。
- description については、v1.3 の prior_art プリセットでは実施形態・背景の記述から重要なバリエーションを拾うために「弱めだが有効なシグナル」として扱う（完全に無効化せず、claims/abstract より軽いが無視はしない程度の重み付けを推奨する）。

**コード制約**

- `fulltext_recall` と同じコード体系（FI/FT or CPC/IPC）を使用し、
  - target_profile の中でも特に重みの高いコードを優先的に用いる。
- 過度に絞りすぎると Recall が落ちるため、
  - FILTER ではなく SHOULD で優先度を上げる形も選択肢とする。

**RRF における位置づけ**

- `fulltext_precision` レーンは RRF 重み $w_\ell$ を高めに設定し、
  - 上位に来た文献を強く押し上げる役割を持たせることが多い。
- 一方で、`fulltext_wide` や `semantic` レーンからも候補が来るため、  
 これらとのバランスを `blend_frontier_codeaware` で調整する。

---

### 3.6 コード専用レーン（オプション）

**目的**

- コード的に「ど真ん中」の文献を、  
  他レーンのスコアに関係なく **少しだけ押し上げるための補助レーン**。

**実装イメージ**

- `target_profile` に基づき、文献ごとにコードスコア $g(d)$ を計算し、  
  それを ZSET として保持する：
  - 例：キー `z:rank_code:{snapshot}` に `{doc_id: g(d)}` を格納
- `blend_frontier_codeaware` の際に、
  - 他のレーンと同様に one lane として扱い、
  - RRF レーン重み $w_{\text{code}}$ を小さめ（例：0.3〜0.5）に設定する。

**注意点**

- コードだけで順位を支配させないために、必ず小さい重みに留める。
- 実装・運用のコストと効果を見て、導入するかどうかを決めればよいオプション扱い。

---

### 3.7 レーン設計の運用パターン

RRFusion MCP v1.3 の標準的な運用パターン（JP/先行技術サーチを想定）は次の通りです。

1. `fulltext_wide` で広く当たりを取り、  
   - その結果から `target_profile`（FI/FT または CPC/IPC のいずれか一体系）を作成する。
2. `fulltext_recall` / `fulltext_precision` / `semantic` を in-field レーンとして設計し、  
   - 初回の in-field パスでは、これら 2〜3 レーンを multi-lane でまとめて実行する（`run_multilane_search`）。
3. `fulltext_recall` で、`target_profile` を使ってターゲット分野を厚く拾う（claims＋abstract＋description）。
4. `fulltext_precision` で、本命候補を絞り込む（claims を中心にしつつ、description も弱めに効かせる）。
5. `semantic` レーンで、「部分遮蔽」「背景説明」などクレームからは拾いにくい概念的な近接候補を補完する。
6. JP/先行技術サーチでは、`fulltext_wide` は原則として **コードプロファイル用＋安全ネット** として扱い、  
   - 初回 fusion には含めず、recall 不足が明らかになったときに code-aware gating を強く効かせた上で追加する。
7. コード専用レーンはオプション機能であり、v1.3 の prior_art プリセットではデフォルトでは使わない（将来の `claim_focus` など別プリセットで導入する余地として残す）。

これらのレーンをまとめて `blend_frontier_codeaware` に渡し、  
RRF + コード情報による融合スコアを得る、というのが v1.3 の基本設計です。

---
## 4. パイプライン全体のフロー（7ステップ）

ここでは、RRFusion MCP のパイプラインを「実際の処理順」に沿って整理します。

---

### Step 1. Feature Extraction（特徴語抽出）

- 入力：ユーザの自然文（+ 必要ならクレーム文）
- LLM の作業：
  - 技術課題の抽出
  - 解決手段の主要構成の抽出（A/B/C…）
  - 同義語・言い換えの整理
  - 明らかに範囲外のもの（negative hints）の明示
  - フィールド重み付けのヒント（claims を重く、abstract を重め…など）

結果として、LLM 内部では次のような「プロファイル」ができるイメージです：

```yaml
feature_terms:
  - "light-emitting element"
  - "drive current control"
  - "temperature sensor"
synonym_clusters:
  - ["light-emitting element", "emission element", "LED element"]
  - ["drive current control", "driving current regulation"]
negative_hints:
  - "display panel"
  - "projector"
field_hints:
  - emphasize_claims: true
  - emphasize_abstract: true
```

このプロファイルをもとに、以降の Step 2〜4 で各レーン向けのクエリを具体化します。

---

### Step 2. Wide Keyword Recall（`fulltext_wide`）

ここでは、「まず大きな網を張る」ために **キーワード中心の wide レーン（`fulltext_wide`）だけ** を実行し、  
後続のコード解析や in-field レーン設計の母集団（wide pool）を作ります。

1. `fulltext_wide` レーン（`search_fulltext`）

   - クエリ：
     - feature_terms ＋ synonym_clusters を広く含むキーワード／Boolean 式
     - negative_hints はできる範囲で除外条件として反映（NOT / must_not）
   - フィールド：
     - title, abstract, claims, description を広く対象とする
   - コード制約：
     - 原則なし（技術分野の先入観を避ける）
   - 実行：
     - `search_fulltext` を呼び、`fulltext_wide` レーン用の `run_id_fulltext_wide` を得る
     - この `run_id_fulltext_wide` を **レーン名と紐付けて保存** しておく

2. wide pool の構成

   - `run_id_fulltext_wide` の上位数百件を、「この問題に関係しそうな分野の粗い候補集合（wide pool）」として扱う
   - 以降の Step 3〜5 で、この wide pool を材料にコード解析・in-field レーン設計・融合を行う
   - semantic レーンによる概念的な補完は、**Step 4 の in-field multi-lane バッチ（`fulltext_recall` / `fulltext_precision` と組み合わせた最初のセット）で追加する**。wide フェーズでは semantic をまだ走らせず、`target_profile` 構築後に必要な scope・観点を絞り込んだうえで semantic を使う。

---

### Step 3. Code Profiling & target_profile 構築

ここでは、`fulltext_wide` レーンの結果を使って「この問題が属する技術分野の輪郭」をコードベースで把握し、  
`target_profile` を構築します。

1. `get_provenance` によるコード分布の取得

   - 入力：
     - `run_id_fulltext_wide`（Step 2 で得た wide レーンの run）
   - `get_provenance(run_id_fulltext_wide)` を呼び、
     - FI/FT/CPC/IPC のコード頻度分布（文献集合ごとの出現頻度）を取得する
       - FT 項目は Patentfield の `fterms` 列（Fタームタグ）から収集されるため、`target_profile` の `F-term:...` もこの列を参照して得られる

2. `target_profile` の構築（LLM ロジック）

   - `get_provenance` のコード頻度辞書をもとに、LLM 側で次を行う：
     - 技術的に意味のありそうなコードを抽出
     - 頻度×特異度（IDF 的な考え方）でスコアリング
     - 上位 n 個（例：10〜30 個）に絞る
   - 結果として、次のような辞書を得る：

   ```yaml
   target_profile:
     "F-term:5F044AA01": 0.9
     "FI:H01L33/00": 0.8
     "FI:H01L33/20": 0.7
     ...
   ```

   - `F-term:...` のようなエントリは Patentfield の `fterms` 列（Fタームタグ）から取得され、`target_profile` の FT 部分に対応する

   - 以降の Step 4〜5 では、この `target_profile` を使って
     - in-field fulltext / semantic レーン（recall / precision / conceptual）のコード制約
     - RRF のコード-aware 調整
     を行う。

---

### Step 4. In-field Lanes（再現・精度・semantic レーン）

Step 3 で得た `target_profile` を用いて、  
`fulltext_recall` と `fulltext_precision` を中心とする in-field レーン群を構築し、  
最初の in-field パスでは semantic レーンも含めた multi-lane バッチを 1 度実行します。

#### 4.1 `fulltext_recall` レーン

- 目的：
  - target_profile が示す技術分野を **厚くカバー** する（Recall 重視）
- クエリ：
  - feature_terms ＋ synonym_clusters を広く使った OR/AND 構造
  - 「用途」「構造」「動作」など、分野を規定する要素を網羅的に含める
- コード制約：
  - `target_profile` から選んだコード体系（FI/FT または CPC/IPC のどれか一体系）を使用
  - その体系内のコードを FILTER または SHOULD でクエリに組み込む
- フィールド：
  - claims＋abstract＋description の関連部分を対象
- 実行：
  - `search_fulltext` を呼んで `run_id_fulltext_recall` を得る
  - この `run_id_fulltext_recall` を **`fulltext_recall` レーンと紐付けて保存** する

#### 4.2 `fulltext_precision` レーン

- 目的：
  - `fulltext_recall` で厚く拾った分野の中から、**本命候補** を絞り込む（Precision 重視）
- クエリ：
  - LLM がクレームチャート的に整理した構成要素をもとに、
    - A：必須構成要素
    - B：重要な限定要素
    - C：好適例（あれば）
  に分け、A＋B を AND 必須、C は SHOULD とするような形で構成
- コード制約：
  - `fulltext_recall` と同じコード体系を使用
  - `target_profile` のうち特に重みの高いコードを優先的に使う
- フィールド：
  - claims を最重視、abstract を補助的に利用
- 実行：
  - `search_fulltext` を呼んで `run_id_fulltext_precision` を得る
  - この `run_id_fulltext_precision` を **`fulltext_precision` レーンと紐付けて保存** する

---

### Step 5. Fusion（RRF + コード志向）

ここまでで、少なくとも次の run_id が揃っています：

- `run_id_fulltext_recall`
- `run_id_fulltext_precision`
- （通常は）Step 4 の最初の in-field バッチで実行した semantic レーンの run_id（例：`run_id_semantic_infield`）
- （任意）wide レーン（`fulltext_wide`）やコード専用レーンの run_id

これらを `blend_frontier_codeaware` に渡し、RRF + コード情報に基づく融合を行います。

1. 入力パラメータの例

```yaml
runs:
  semantic:             run_id_semantic_infield   # 最初の in-field バッチで実行した semantic レーン（存在する場合）
  fulltext_recall:      run_id_fulltext_recall
  fulltext_precision:   run_id_fulltext_precision
  # optional:
  # fulltext_wide:      run_id_fulltext_wide      # recall 不足時に code-aware gating 付きで安全ネットとして追加する
  # optional:
  # code_lane:          run_id_code_only
weights:
  fulltext_wide:      0.8
  semantic:           0.7
  fulltext_recall:    1.0
  fulltext_precision: 1.4
  # code_lane:        0.3
rrf_k: 80
beta_fuse: 1.5
target_profile: {...}  # Step 3 で構築したもの
```

- `weights`：
  - レーンごとの RRF 重み $w_\ell$
- `rrf_k`：
  - RRF の k パラメータ
- `beta_fuse`：
  - Fβ の β に相当する、「Recall/Precision のバランス」を調整するパラメータ
  - レーンの融合結果を「再現寄り」にするか「精度寄り」にするかを調整するパラメータです。
    F値の `Fβ` における β と同様に、
    - `beta_fuse > 1` なら再現寄りになります
    - `beta_fuse < 1` なら精度寄りになります
    - `beta_fuse = 1` なら両者をバランスよく扱います
    という振る舞いをします。
    ただし、これは評価指標としての β そのものではなく、
    **ランク融合（fusion）アルゴリズム側の「好み」を決めるハイパーパラメータ** である点に注意してください。
    ここでいう `fuse` は、英語の動詞 *to fuse*（融合する・合成する）の意味で、複数の検索レーンの結果を 1 本のランキングに「融合（rank fusion）」する処理を指します。
- `target_profile`：
  - コード-aware なスコア調整に利用するコード重み辞書

2. 出力

- `blend_frontier_codeaware` は、
  - 融合済みランキングを表す新しい `run_id_blend` を返す
- 以降の Step 6〜7 では、この `run_id_blend` をもとに
  - スニペット確認
  - パラメータチューニング
  を行う

---

### Step 6. Snippet Budgeting & Human / LLM Review

ここでは、`run_id_blend` を人間が確認しやすい形に落とし込むためのステップです。

LLM エージェント側でもこのステップを踏むことが前提ですが、実務上は `peek_snippets` で上位を軽く確認しながら Redis の doc キャッシュを温め、`get_snippets` で選んだ候補の詳細（特に desc）を厚めに取るという使い分けをする想定です。`peek_snippets` は title 80, abstract 320, claim 320 文字程度の限られた箇所を見て候補感を掴み、`get_snippets` では claims 800 文字＋description 800 文字程度を `per_field_chars` で指定して精読する、といった流れがプロンプト予算と API レイテンシのバランスを保つコツです。Redis の doc キャッシュ（`h:doc:{doc_id}`）には snippet_ttl_hours（現在 1 時間）で TTL が設定されており、短時間内は peek/get の結果が再利用されます。

#### 6.1 `peek_snippets` による軽量ビュー（任意）

- 目的：
  - 上位 30〜50 件程度を「薄く広く」眺めて、  
    - 「顔ぶれが妥当か？」
    - 「分野外が多すぎないか？」
    - 「請求項の書きぶりが期待に近いか？」
    を短時間で掴む
- 呼び出し例：

```jsonc
{
  "tool": "peek_snippets",
  "arguments": {
    "run_id": "run_id_blend",
    "offset": 0,
    "limit": 50,
    "fields": ["claim", "abst"],
    "budget_bytes": 800
  }
}
```

- `fields` とレスポンスの対応：
  - 例では `["claim", "abst"]` を指定した場合、
    - レスポンス側の各スニペットは `"fields": { "claim": "...", "abst": "..." }` のように、同じキーを持つ

- 運用ポリシー（推奨）：
  - `peek_snippets` は必要なときだけ使い、通常は直接 `get_snippets` で上位候補を読む。
  - `peek_snippets` を使う場合も、「上位 30〜50 件をざっと確認して候補を絞る」軽い用途に限定し、テキストの精読および description の確認は `get_snippets` 側で行う。
  - `peek_snippets` が返すフィールドがすべて空文字列（`""`）になっている場合は、Redis 側にタイトル等が一度もキャッシュされておらず、かつ backend への `fetch_snippets` 呼び出しが失敗している可能性が高い。通常は `missing_ids` に対して backend からテキストを取得し `upsert_docs` するため、1 回目の peek でも少なくとも一部のフィールドには文字列が入るのが正常である。

#### 6.2 `get_snippets` による詳細ビュー

 - 目的：
   - 上位候補の中で、「本当に読み込むべき文献」を選ぶために  
     description を含めた詳細をしっかり確認する
- 呼び出し例：

```jsonc
{
  "tool": "get_snippets",
  "arguments": {
    "ids": ["JP1234567A", "US2020123456A1", "..."],
    "fields": ["claim", "abst"],
    "per_field_chars": {
      "claim": 2000,
      "abst": 1000
    }
  }
}
```

- `fields`：
  - 返すフィールドには description (`desc`) を含めるのが望ましく、claims/abst/desc を同時に指定することで merged doc を得られる。
- `per_field_chars`：
  - 項目ごとの文字数上限。`peek_snippets` は総バイト `budget_bytes` を優先するため `get_snippets` では `per_field_chars` で厚めに指定するとよい（例: claim 800, desc 800, abst 480）。

 このように、

- `peek_snippets`：広く薄く
- `get_snippets`：狭く厚く

 という 2 段階で、`run_id_blend` の上位を人間がレビューできるようにします。

#### Snippet backend selection
- Snippet retrieval always targets the lane defined by `SNIPPET_BACKEND_LANE` (default `fulltext`). Even fusion runs without lane metadata use this configured backend, so peek/get can fetch text consistently through the same API (Patentfield in CI). Adjusting `SNIPPET_BACKEND_LANE` lets you swap in a different snippet backend without changing the tool flow.

### 6.3 Representative-document review

Representative review is an **optional, heavier human-in-the-loop step** that is only proposed when lighter tuning (mutate_run + peek_snippets) has failed to improve the frontier or top candidates.

- Trigger: after at least two mutate_run cycles on the same fusion run, and only when the frontier and top-ranked candidates have changed little and the human explicitly indicates they want deeper tuning.
- Selection: combine the fused ranking (`pairs_top`) with several semantic-high examples so that both lexical and conceptual matches are exposed, and select **exactly 30 candidates** in total.
- Fetch: use `get_snippets` with `fields=["claim","abst","desc"]` and `per_field_chars={"claim":1000,"abst":600,"desc":1200}` so the human can read a consistent chunk of text without overwhelming Redis.
- Labeling: categorize each doc as  
  * A – high fused rank and clear match to the core concept,  
  * B – lower rank but still topically appropriate,  
  * C – otherwise (off-topic or too distant).  
- Presentation: summarize how many attendees are in each bucket and highlight 1–2 examples from A/B. Ask the human whether to treat A alone or A+B as accepted correspondences before proceeding to tuning.  
- When the system considers expanding to non-JP pipelines (e.g., after adding >3 manual in-field searches with no coverage gain), re-run this representative 30-document review and present the results alongside the question about launching the WO/EP/US pipeline so the human can see what the current JP set looks like before deciding.

### 6.4 Representative feedback, facet weighting, and fallback search regeneration

- Convert `synonym_clusters` from Step 1 into the `facet_terms` payload that goes into every fusion request, grouping the same technical idea under a single facet (A/B/C) and including multiple synonymous expressions within that facet so `compute_facet_score` can reward semantic coverage. 代表レビューで得た A/B の判断もこの facet 情報とセットで扱い、`facet_weights` の値をレビュー後の判断に応じて書き換えます。たとえば `facet_weights["A"]` を引き上げて `pi′(d)` が A に素直に反応するようにしたり、B を含めて採用する場合は B を含む synonym_cluster を厚めにする、といった運用が想定されます。
- 代表レビューの結果を基にした A/B の採用範囲が上位候補の受け入れ条件です。人間が「A のみ」受け入れると答えたときは facet_weights で A を重くし、B と C の重みを落としたうえで `pi_weights` の B 信号を抑えてください。A+B を受け入れると返答したときは B を含む facet_terms を厚くし、A と B の両方が一定以上のスコアを獲得するように `pi_weights` を調整します。代表レビューは、初期段階では上位 20 件程度の「軽めの 20-document review」を何度か繰り返して傾向を把握し、フロンティアが安定してきたタイミングで **30 件の代表セット** を固定する、という二段階運用を想定しています。
- 代表レビューで C しか残らず A/B が得られなかった場合は、現在の fusion 構成を一度リセットしてフォールバック検索を走らせます。具体的には、Step 1〜4（feature_extraction → fulltext_wide → code_profiling → infield_lanes）を見直し、新しい synonym_clusters や field_hints を反映したキーワード／semantic 式を再構築し、それらで再度 run を取得してから blend_frontier_codeaware を呼び直します。`mutate_run` による微調整はこの再スタートの後、「A/B の範囲が確認できたとき」に実行してください。WO/EP/US パイプラインへ展開するかを検討する際も、直前に 20 件程度の代表レビューをやり直し、現在の JP セットの妥当性を確認してから判断するのが望ましい運用です。
- このフォールバック検索サイクルを終えるまで、非JP パイプライン（WO/EP/US）への展開は提案せず、必要があれば代表レビュー結果を人間に再提示してから追加の corpus を検討してください。

---

#### 6.5 キャッシュ拡張案：REST + Redis 再利用

- 現状 `PatentfieldBackend`/`HttpLaneBackend` は `httpx.AsyncClient` を直接使っているため、同一クエリ・filters・fields・lane でも毎回 Patentfield を叩いています。ここに `httpx` の `transport` や `event_hooks` を使ったキャッシュアダプタを挟み、クエリと構成パラメータを正規化したキー（例：`fields` をソート・`sort_keys` を含める）で Redis やローカルストレージに TTL 付きで保存する実装にすれば、REST レベルでの重複呼び出しを減らせます。
  - 既存ライブラリ（`httpx-cache`, `httpx-cache-control` など）を `HttpLaneBackend` の AsyncClient 初期化時に組み込めば、最小限のコード変更でキャッシュが効きます。401/5xx のようなエラー時にはキャッシュを使わず再フェッチし、成功時は TTL を挟んで更新するルールを明示するのが実装例です。
  - クエリのハッシュ化に `hash_query`（`src/rrfusion/utils.py`）を再利用し、`fields` や `filters` まで含めた総合キーを生成しておけば、同じパラメータを利用したときにキャッシュがヒットしやすくなります。

- 現在の `RedisStorage.store_lane_run` は `query_hash`（クエリ＋filters）＋ `lane` で `z:<snapshot>:<query_hash>:<lane>` のスコアセットとドキュメントハッシュを保存し、後続 `blend_frontier_codeaware` は `zslice`/`get_docs` で再利用しています（`src/rrfusion/storage.py:42-220`）。この仕組みを前倒しして、lane 実行前に同じ `query_hash` が存在すれば `SearchToolResponse` をそのまま再利用するパスを追加すると、`run_id` を新たに切らなくてもキャッシュヒットが可能です。
#### コード語彙によるキャッシュ圧縮

- `RedisStorage` 内部で `code_vocab:{snapshot}` と `code_vocab_rev:{snapshot}` を管理し、分類コード（IPC/CPC/FI/FT/F-term）を整数 ID に置き換えて格納するようにしました。これにより Redis への `doc` フィールド保存時の文字列サイズを抑えつつ、`get_docs` 時には逆引きして元のコード文字列を復元できます（`src/rrfusion/storage.py:36-220`）。
- レーン実行では、全ドキュメントに含まれるコードをまとめて辞書化し、`store_lane_run` ではその ID 列を `json.dumps` して保存。`get_docs` は request ごとにコード ID を読み出し、キャッシュ済みの逆マップまたは Redis から引いた文字列で復元します。これにより `doc` キャッシュの平均サイズが下がり、F-term を含むコード頻度のキャッシュも軽量になります。
  - さらに `peek_snippets`/`get_snippets` で `_fetch_snippets_from_backend` によって不足分を追加したり `upsert_docs` で更新している現行ロジック（`src/rrfusion/mcp/service.py:520-694`）と組み合わせれば、スニペットの鮮度を損なわずに段階的なキャッシュ強化ができます。

### Step 7. Frontier Tuning（フロンティア調整）

最後に、`mutate_run` と `get_provenance` を使って、  
RRFusion MCP の設定を「手応えのあるフロンティア」にチューニングします。

ここでいう「フロンティア」とは、  
検索設定（レーン重みや beta_fuse など）をいくら変えても、これ以上は

- 再現率（Recall）を上げれば適合率（Precision）が下がり、
- 適合率を上げれば再現率が下がる

という **限界のトレードオフ曲線** を指します。

1. `mutate_run` によるパラメータ変更

- 入力：
  - 元となる `run_id_blend`
  - 変更後パラメータを表す `delta`（※名称は delta だが、**差分ではなく絶対値指定**）

```jsonc
{
  "tool": "mutate_run",
  "arguments": {
    "run_id": "run_id_blend",
    "delta": {
      "weights": {
        "fulltext_precision": 1.6,
        "semantic": 0.8
      },
      "rrf_k": 90,
      "beta_fuse": 1.7
    }
  }
}
```

- ここでの `delta` は：
  - 「元の値に対する±の差分」ではなく、
  - 「変更後の **絶対値** を上書きする指定」である点に注意
- 出力：
  - 新しい設定で再計算した run（例：`run_id_blend_2`）が返ってくる

2. `get_provenance` による寄与度・コード分布の確認

- 各 `run_id`（`run_id_blend`, `run_id_blend_2`, ...）について `get_provenance` を呼び、
  - レーンごとの寄与度（例：`{"fulltext_recall": 0.3, "fulltext_precision": 0.5, "semantic": 0.2}`）
  - コード分布（`target_profile` との整合度）
  を確認する

3. `peek_snippets` / `get_snippets` による比較

- 新旧それぞれの run_id について `peek_snippets` を呼び、
  - 上位の顔ぶれがどう変わったか
  - 分野外文献の混入具合がどう変わったか
  を確認する
- 必要なら `get_snippets` で上位候補を詳しく比較する

4. 設定の固定

- 上記のサイクル（`mutate_run` → `get_provenance` → `peek_snippets`）を数回繰り返し、
  - 実務家の感覚と proxy 指標（コード分布など）が両立する設定を「レシピ」として固定する

---

このように、Step 1〜7 を一連のフローとして回すことで、

- wide〜precision〜semantic の各レーンを
- target_profile と Fβ 志向の融合ロジックで統合しつつ
- 人間のレビューとチューニングループを組み込み

「ラベルなし環境でも、それなりに信頼できる検索フロンティア」を構築することを狙っています。

---

### 5.2 「うまくいっていない」ことを検知する評価指標（アラーム）

v1.3 の SystemPrompt と MCP ツール群を前提としたとき、次のような観測値は「検索がうまくいっていない可能性が高い」**代表的な赤信号の例**として扱えます。  
ここに列挙されている条件はあくまで例示であり、これらに該当しない場合でも、実務家の感覚や個別タスクの事情に応じて「おかしい」と判断されるパターンがあれば、その都度 SystemPrompt やレーン設計の見直し対象になり得ます。

- **wide レーンのヒット件数・クエリ構造**
  - `fulltext_wide` の `count_returned` が `top_k≈800` に対して **100 件未満** の場合、wide 側で AND/NOT が強すぎる可能性が高い。
  - wide クエリに用途・シーン（ゲート、入退室管理、車載など）が AND/MUST で入っている場合は、用途で絞り込みすぎているサインとして扱う。
  - 対応方針：用途語を一度 SHOULD/OR に落とした wide クエリ候補を作り直し、ヒット件数と code_freqs の変化を比較する。

- **コード分布（target_profile）が用途側に偏りすぎている**
  - `get_provenance` で `fulltext_wide` の `code_distributions` を見たときに、用途テーマ（ゲート系、特定アプリケーション限定のテーマなど）の FI/FT ばかりが上位を占め、コア技術側のコードがほとんど現れない場合。
  - 対応方針：feature_extraction で用途語を C（用途・シーン）に明示的に分離し、A/B（コア技術）のみで wide/in-field クエリの骨格を再構築する。

- **レーン寄与の極端な片寄り**
  - `blend_frontier_codeaware` 後の `lane_contributions`（`get_provenance`）で、特定の 1 レーンが 0.8〜0.9 以上を占め、他レーンの寄与がほぼゼロになっている場合。
  - 特に `fulltext_precision` や用途付きの in-field レーンだけが支配的になっているときは、precision バイアスに寄り過ぎて広い候補が死んでいる可能性がある。
  - 対応方針：`mutate_run` で当該レーンの weight を下げ、recall 寄りレーン（wide/recall/semantic）の weight を少し引き上げて frontier の形（Fβ）と代表レビューを再確認する。

- **frontier の形がフラットで Fβ が立ち上がらない**
  - `BlendResponse.frontier` の `F_beta_star` が、k を増やしてもほとんど改善しない（例えば k=10〜50 で 0.1〜0.2 のフラットな線に張り付いている）場合。
  - 対応方針：  
    - wide / in-field のクエリ設計を見直し（特に AND/NOT の強さとフィールド選択）、  
    - semantic レーンの feature_scope を変える（claims-only → wide など）  
    といった「レーン側の情報供給」を疑う。mutate_run だけで frontier を改善しようとしない。

- **代表レビューの A/B がほとんど得られない**
  - 代表 20/30 件のレビューで A/B がほとんどなく C（off-topic）が多数を占める場合、現在の fusion 設定ではコア技術の prior art に十分到達できていない。
  - 代表 A/B の多くが特定用途（例：ゲート付き）に偏っている一方で、実務上重要な「用途違いの広義 prior art」が含まれていないと判断された場合も赤信号。
  - 対応方針：feature_extraction〜wide〜code_profiling まで一度戻り、「コア技術」と「用途」の分離・用途語を含まない wide/in-field レーンの追加を検討する。

- **スニペットの顔ぶれが明らかに off-field**
  - `peek_snippets` を wide や fulltext_recall に対して実行したとき、上位 20〜30 件の多くが、専門家の目から見て明らかに分野外（コードもテキストも合っていない）になっている場合。
  - 対応方針：  
    - FI/FT フィルタの再設計（近いコードの OR グループにしつつ、明らかな off-field コードを negative hints として扱う）  
    - feature_terms / synonym_clusters から一般語を減らし、コア技術語を厚くする  
    など、「クエリ設計」側を優先的に見直す。

これらのアラームは、単独で「失敗」と決めつけるものではなく、「mutate_run での微調整ではなく、レーン設計や feature_extraction に戻るべきか」を判断するトリガとして扱います。  
また、ここで挙げた条件に完全には当てはまらなくても、検索プロが「結果セットの顔ぶれやコード分布がおかしい」と感じた場合は、それ自体をアラームとして扱い、同様に wide / in-field / feature_extraction の見直しを検討してよいものとします。

---

### 5.3 今後の改善ポイント

RRFusion MCP v1.3 は、wide → in-field → fusion → snippets → tuning という骨格は安定しているものの、feature_extraction と wide/in-field 設計に大きく依存するため、今後の改善余地をいくつかの観点から整理しておきます。

#### 5.3.1 評価・運用・プロンプト側の改善

- **用途語とコア技術語のガイドテーブル**
  - 顔認証ゲートのような個別例に依存しない形で、「用途語候補」「コア技術語候補」の例をドメイン別に整理し、SystemPrompt の参照テーブルとして持つ。
  - LLM が feature_extraction で A/B/C を割り振る際に、「用途語を A に入れにくくする」方向のバイアスを持たせる。

- **wide 検索の自動ヘルスチェック**
  - `count_returned` と code_freqs を見て、
    - ヒットが少なすぎる
    - コード分布が用途側テーマに偏りすぎている
    場合に、SystemPrompt 側で「用途語を外した wide 再検索候補」を 1〜2 パターン自動生成し、ユーザに選択させるフローを標準化する。

- **用途あり／なしの in-field ペアレーン設計**
  - in-field フェーズでは、少なくとも次の 2 種類の論理レーンをテンプレートとして用意する：
    - コア技術のみ（A/B）を対象とするレーン
    - コア技術＋代表的用途（A/B/C）を対象とするレーン
  - fusion の initial_weights では、用途付きレーンの重みを少し軽めに設定し、用途語による過度なバイアスを抑える。

- **代表レビュー結果のフィードバック**
  - 代表 30 件の A/B/C ラベルと lane_contributions を継続的に記録し、
    - A の多くがどのレーンに支えられているか
    - C が多いレーンの共通パターン（用途語過多、コード過剰など）
    を観察する。
  - これをもとに、SystemPrompt のデフォルト weight や query_style（例えば fulltext_precision の field_boosts）の次バージョンを調整する。

- **ユーザとの用途確認 UX**
  - 新しいタスクの冒頭で、「用途は例示か、必須条件か」を A/B のような選択肢でユーザに明示的に聞き、A（例示）の場合は wide/in-field で用途語を自動的に SHOULD に落とす。

#### 5.3.2 システム実装側の改善

- **クエリ構造のログとアンチパターン検出**
  - `search_fulltext` / `search_semantic` に渡した実クエリ（Boolean 式／自然文）を構造化してログに残し、
    - AND のネストが深すぎる
    - 用途語が MUST に入っている
    といったアンチパターンを自動検出するヘルパを用意する。
  - debug モードでは、この検知結果を短い debug ノートとして LLM に返し、プロンプト側でクエリ修正を促す。

- **wide の再検索サイクル用ユーティリティ**
  - 既存の `hash_query` や `RedisStorage` の `query_hash` を活用し、「用途語を外した変種 wide クエリ」を試すときに、  
    - どのクエリバリアントでどのコード分布・frontier が得られたか  
    を比較しやすくするメタデータ記録／可視化 API を検討する。

- **semantic レーンの feature_scope チューニング支援**
  - `search_semantic` の `feature_scope` を、claims-only / wide / background_jp などで切り替えたときの frontier 変化を簡単に比較できるテストシナリオ（e2e や integration テスト）を追加し、「semantic に何を期待するか」を仕様レベルで検証できるようにする。

- **代表情報の長期利用とサマリ**
  - `register_representatives` で登録された代表セットを、単なるその場限りの tuning シグナルではなく、「次バージョンの SystemPrompt/レーン設計を見直すためのデータ」として蓄積・分析するツール（簡易レポートスクリプトなど）を追加する。

これらの改善案は、v1.3 の core アーキテクチャを変えずに、「どの段階で何を疑うべきか」「どこからレーン設計に戻るべきか」を明確にすることを目的としている。実装コストと効果を見ながら、wide のヘルスチェックと用途語の扱いの強化から順に進めていくのが現実的なロードマップである。

---

## 5. 典型的な問題パターンと対処

### 5.1 wide レーンで「ノイズ」が多すぎる」

**症状**

- 明らかに分野が違う文献が大量に混ざる
- コード頻度解析で、関係ない分野のコードが大量に出る

**原因候補**

- `fulltext_wide` の OR 展開が広すぎる
- 特徴語の選定が甘く、一般語が多い

**対処（v1.3, JP/先行技術サーチを想定）**

- **役割分担を明確にする**
  - `fulltext_wide` は「コードプロファイリング用の wide 母集団」として位置付け、JP 先行技術サーチでは **初期 fusion に必ずしも含めない**。
  - まずは `fulltext_recall` / `fulltext_precision` / `semantic` の in-field トラックだけで fusion を組み、Recall/Precision のバランスを確認する。
- **wide を safety net として限定的に使う**
  - 上記の in-field fusion とスニペットレビューの結果、「明らかに recall が足りない」「FI/FT だけでは拾えていない周辺技術がある」と判断された場合に限り、
    - `fulltext_wide` を追加の run として `blend_frontier_codeaware` に渡す。
    - このとき、`target_profile` による code-aware gating を強く効かせ、「target_profile によく一致するコードを持つ wide 文献だけをブーストし、オフプロファイルな wide 文献はスコアを大きく下げる」ようにする。
- **クエリ設計の見直し**
  - それでも wide 側の FI/FT 分布が明らかにおかしい場合は、
    - `feature_terms` / `synonym_clusters` を見直して一般語を減らす
    - negative hints を追加し、用途や分野が明らかに違うものを NOT で弾く
  といったクエリ調整を行う。

このように、`fulltext_wide` を「常に fusion の一員」としてではなく、「コードプロファイル＋必要なときだけ safety net」として扱うことで、ノイズを抑えつつ wide の利点を活かせる。

### 5.4 precision が不足している

**症状**

- 上位 50～100 件を見ても「本当に欲しい文献」がなかなか出てこない

**原因候補**

- `fulltext_precision` で phrase / NEAR をあまり使っていない
- claims へのフィールドバイアスが弱い

**対処**

- claims 内の重要構成を明確にし、その組み合わせを NEAR で表現
- synonym cluster の中から「強い言い方」を優先的に使う
- weights で `fulltext_precision` の重みを上げる

---

## 6. アルゴリズム & ヒューリスティクス（最終実装）

この節では、RRFusion MCP v1.3 で実際に採用している実装レベルのロジックを示します。  
ここまでの説明で出てきた概念（RRF、target_profile、コード頻度など）が、  
**どのような数式・Redis操作として具現化されているか** を明示します。

### 6.1 RRFスコアリングと格納

各レーン（`search_fulltext` / `search_semantic` など）で検索を実行した結果に対して、  
**ランクベースのスコア** を以下の式で計算します。

\[
\text{score}_\ell(d) = \frac{w_\ell}{\text{rrf\_k} + \text{rank}_\ell(d)}
\]

- $\ell$：レーン（`fulltext_wide`, `semantic`, `fulltext_recall`, `fulltext_precision`, ...）
- $w_\ell$：レーンの重み（後述の lane weights）
- $\text{rank}_\ell(d)$：レーン $\ell$ における文書 $d$ の順位（1始まり）
- `rrf_k`：RRF の調整パラメータ（60〜120 程度）

実装上は：

- 各 `search_*` 呼び出し時に上記スコアを計算し、Redis の ZSET に格納する  
  - キー例：`z:{snapshot}:{query_hash}:{lane}`  
- 同時に、後続処理用に「文書別スニペット」「コードリスト」も Redis にキャッシュしておく。

複数レーンの結果を融合するときは、Redis の `ZUNIONSTORE` を用いて、

- 各レーン ZSET をまとめて `z:rrf:{run_id}` に ZUNION する
- WEIGHTS は 1 固定（すでに `score_ℓ(d)` の中に `w_ℓ` が織り込まれている）

という形で RRF 融合を実現しています。

#### 実装メモ（現行バージョン）

上記は「最終的に到達したい実装イメージ」であり、現行バージョンではもう少し素朴な構成になっています。

- レーン検索（`search_fulltext` / `search_semantic` など）では、DB stub から返されたスコアをそのまま ZSET に格納しており、  
  RRF 用の $\text{score}_\ell(d)$ は **fusion 時に Python 側で計算** しています  
  - 実装では `compute_rrf_scores`（`src/rrfusion/fusion.py`）で、各レーンの順位と `weights` に基づいて RRF スコアを計算しています
- 計算した fused スコアは、`store_rrf_run`（`src/rrfusion/storage.py`）を通じて `z:rrf:{run_id}` に保存されます
- Redis の `ZUNIONSTORE` を用いたレーン ZSET 同士の直接的な加算は、現行実装ではまだ行っていません

したがって、式やキー構造はそのまま活かしつつも、

- 「RRF-ready なスコアをあらかじめ各レーン ZSET に格納する」
- 「fusion は Redis 側の ZUNIONSTORE だけで完結させる」

といった設計は **将来の拡張候補** として位置付けています。

---

### 6.2 コード情報に基づくスコア調整（Code-aware adjustments）

`target_profile` は、技術分野ごとのコード重み（FI/FT/CPC/IPC）を表す

\[
T = \{\, c \mapsto T_c \,\}
\]

のような辞書です。  
`get_provenance` が返すコード頻度辞書をベースに、LLM 側ロジックで `T_c` を決めておきます  
（頻度×特異度、上位コードのみ残す、などのヒューリスティクス）。

この `target_profile` を、以下の 3 つの方法で活用します。

#### A) 文献ごとのブースト（Per-doc boost）

まず、文献 $d$ に付与されているコード集合を $\mathcal{C}(d)$ とします。  
この文献が `target_profile` とどの程度重なるかを表すスコア $g(d)$ を計算します。

\[
g(d) = \sum_{c \in \mathcal{C}(d)} T_c \cdot h(c)
\]

- $T_c$：`target_profile` におけるコード $c$ の重み
- $h(c)$：階層マッチの補正等を行う係数  
  （例：完全一致なら 1.0、上位階層一致なら 0.5 など）

この $g(d)$ を [0,1] に正規化したものを $\text{norm}(g(d))$ とし、  
各レーン $\ell$ のスコアを次のように補正します。

\[
\hat{s}_\ell(d) = s_\ell(d) \cdot \left(1 + \alpha_\ell \cdot \text{norm}(g(d))\right)
\]

- $s_\ell(d)$：元の RRF 用スコア
- $\hat{s}_\ell(d)$：コード情報でブーストされたスコア
- $\alpha_\ell$：レーンごとのコード感度パラメータ（0 以上）

**実装メモ**

- `hat_s_ℓ(d)` は ZSET のスコアとして反映される  
- レーンごとに $\alpha_\ell$ を変えることで、  
  「このレーンはコードに敏感／鈍感」といったチューニングが可能  
- $\alpha_\ell$ は内部実装用の固定パラメータであり、MCP ツール引数からは変更できない

#### B) レーン重みの調整（Lane modulation）

各レーン $\ell$ について、そのレーンの結果に含まれるコード頻度を集計して  
コード頻度ベクトル $F_\ell$ を作ります：

\[
F_\ell = \{\, c \mapsto f_{\ell,c} \,\}
\]

- $f_{\ell,c}$：レーン $\ell$ におけるコード $c$ の出現頻度

`target_profile` $T$ と $F_\ell$ の類似度を例えばコサイン類似度で定義します：

\[
\text{sim}(F_\ell, T) =
\frac{\sum_c f_{\ell,c} \cdot T_c}{\sqrt{\sum_c f_{\ell,c}^2} \cdot \sqrt{\sum_c T_c^2}}
\]

これを使ってレーン重みを調整します：

\[
w'_\ell = w_\ell \cdot \left(1 + \beta \cdot \text{sim}(F_\ell, T)\right)
\]

- $w_\ell$：元のレーン重み
- $w'_\ell$：コード適合度を反映した新しいレーン重み
- $\beta$：調整強度（正の値。大きいほど「target_profile に一致するレーン」を優遇）

**実装メモ**

- 実際には、各レーンの ZSET スコアにスケーリングをかける形で反映します
- 例えば `ZUNIONSTORE` でもう一段階 WEIGHTS を使ってスコアを拡大・縮小できます

#### C) コード専用レーン（Code-only lane）

場合によっては、コード情報だけでランキングする補助レーンを作ることもできます。

- 文献ごとの $g(d)$ をスコアとする ZSET（例：`rank_code(d)`）を作り、
- これを小さな重み $w_{\text{code}}$（例：0.5）で融合に加える

これにより、

- 「コード的にど真ん中」の文献が、他のレーンのスコアに関係なく少しだけ押し上がる
- ただし重みは小さく保ち、過度にコードのみで支配されないようにする

#### 実装メモ（現行バージョン）

上記 A〜C は、コード情報を用いたスコア調整の「あるべき姿」を示した設計レベルの説明であり、  
現行バージョンでは、次のような簡易実装になっています。

- A) 文献ごとのブーストについて  
  - 実装では `apply_code_boosts`（`src/rrfusion/fusion.py`）で、文献ごとのコード集合と `target_profile` の重みを用いて  
    「コード重みの総和（boost）」を計算し、それに `weights["code"]` を掛けた値を **加算ブースト** としてスコアに足しています
  - 正規化 $\text{norm}(g(d))$ やレーンごとの感度パラメータ $\alpha_\ell$ は現時点では導入しておらず、  
    乗算ではなく「fused スコアに対する一律の加算」として扱っています

- B) レーン重みの調整について  
  - 各レーンごとのコード頻度 `F_ℓ` は頻度サマリとして Redis に保存していますが、  
    `sim(F_ℓ, T)` による動的な `w'_ℓ` の調整は、現行バージョンではまだ行っていません
  - fusion 時のレーン重みは `BlendRequest.weights` で渡された値をそのまま使用しており、  
    コード分布に応じた自動モジュレーションは **将来拡張** として残しています

- C) コード専用レーンについて  
  - コード情報だけを ZSET として持つ「コード専用レーン」は、現行実装ではまだ導入していません
  - 代わりに、A) の加算ブーストと `contributions[doc_id]["code"]` により、  
    「コード由来の押し上げ」がどの程度効いたかを fusion レベルで把握できるようにしています

このように、コード情報はすでにスコアに反映されていますが、  
設計で述べたような「レーン別の感度パラメータ」や「コード専用レーン」「レーン重みの自動調整」は、  
次期バージョン以降で段階的に取り込むことを想定した **拡張余地** として整理しています。

---

### 6.3 フロンティア推定（Frontier estimation）

`mutate_run` によるパラメータ探索を支えるために、  
「ある設定における精度・再現度の見込み」をプロキシで見積もる仕組みを持ちます。

ある融合スコア $\hat{s}(d)$（例えば A/B/C をすべて反映後の最終スコア）に対して、  
複数の $k$ 値（上位何件までを見るか）からなるグリッド $k_{\text{grid}}$ を用意し、それぞれについて：

- **$P_\ast(k)$**：上位 k 件の「平均的な関連度プロキシ」
- **$R_\ast(k)$**：上位 k 件までの「再現度プロキシ」
- **$F_{\beta,\ast}(k)$**：これらから計算した Fβ 相当値

を算出します。

例として：

\[
\pi'(d) = \sigma(a \cdot \hat{s}(d) + b + \gamma \cdot z(g(d)))
\]

- $\sigma(\cdot)$：シグモイド関数（0〜1の値に圧縮）
- $z(g(d))$：コード重み $g(d)$ に対する変換（標準化など）
- $a,b,\gamma$：調整パラメータ

とおき、$P_\ast(k)$ を、

\[
P_\ast(k) = \frac{1}{k} \sum_{d \in \text{Top-}k} \pi'(d)
\]

のように定義します。

一方、$R_\ast(k)$ は技術分野のカバレッジを proxy として、

\[
R_\ast(k) = \rho \cdot \text{coverage}(k) + (1 - \rho) \cdot \text{CDF\_score}(k)
\]

- $\text{coverage}(k)$：上位 k 件で `target_profile` に含まれるコードがどれだけ多様にカバーされているか
- $\text{CDF\_score}(k)$：スコアの累積分布に基づく指標（詳細は実装依存）
- $\rho$：カバレッジとスコアのバランスを決める係数

最後に、通常の Fβ の式を使って $F_{\beta,\ast}(k)$ を求めます：

\[
F_{\beta,\ast}(k) = (1+\beta^2) \cdot \frac{P_\ast(k) \cdot R_\ast(k)}{\beta^2 \cdot P_\ast(k) + R_\ast(k)}
\]

グリッド上の 10〜20 点程度の代表点についてこの値を計算し、  
「どのあたりの k でバランスが良いか」を可視化します。

#### 実装メモ（現行バージョン）

上記の $\pi'(d)$ によるシグモイド型のプロキシは、現時点では **将来拡張案** であり、  
実装ではもう少し素朴な形でフロンティアを計算しています。

- `target_profile` に基づいて、各文献ごとに「コード一致度スコア」を計算する  
  - 実装では `compute_code_scores`（`src/rrfusion/fusion.py`）で、  
    IPC/CPC/FI/FT それぞれについて `target_profile` の重みを合計し、最大値で正規化した値（0〜1）を `code_scores[doc_id]` としている
- 指定された $k_{\text{grid}}$ それぞれについて、上位 k 件における  
  - $P_\ast(k)$：top-k の `code_scores` の平均値（「コード的な正しさ」の平均）
  - $R_\ast(k)$：top-k の `code_scores` の総和 / 全文献の `code_scores` の総和（「コード的に見た coverage」）
  を計算し、通常の Fβ 式で $F_{\beta,\ast}(k)$ を求める  
  - 実装では `compute_frontier`（`src/rrfusion/fusion.py`）で計算している

このため、現行実装の $P_\ast(k), R_\ast(k), F_{\beta,\ast}(k)$ は、

- コード分布に基づいて、「どのくらい target_profile に沿った文献が上位に集中しているか」「どのくらい target_profile をカバーできているか」を見る **簡易版の proxy**

として動作しており、  
将来的にはここで説明したシグモイド変換や coverage ベースの指標、クエリ要素カバレッジなども組み合わせた、よりリッチな $\pi'(d)$ へ置き換える余地があります。

---

### 6.4 レーン別貢献度のトラッキング

最後に、`get_provenance` から返す情報として、  
**各レーンが文献スコアにどれくらい寄与したか** を記録します。

- RRF スコアを計算する過程で、
  - 文献 $d$ のスコアが、
    - `fulltext_recall` レーン由来でどれだけ増えたか
    - `fulltext_precision` レーン由来でどれだけ増えたか
    - `semantic` レーン由来でどれだけ増えたか
    - `code` レーン（もしあれば）由来でどれだけ増えたか
  を積算していきます。

- 最後に、各文献ごとに寄与度を正規化して **百分率** に変換し、
  - 例：`{ "fulltext_recall": 0.2, "fulltext_precision": 0.5, "semantic": 0.3 }`
  のような形で `get_provenance` の結果に含めます。

これにより、チューニング時に：

- 「この設定だと precision レーンが支配的になりすぎていないか」
- 「semantic レーンの寄与がほとんどゼロになっていないか」

といった診断がしやすくなります。

#### 実装メモ（現行バージョン）

現行バージョンでは、レーン別貢献度のトラッキングは次のような形で簡易的に実装されています。

- RRF 計算時に、レーンごとの寄与を `contributions` として積算しています  
  - 実装では `compute_rrf_scores`（`src/rrfusion/fusion.py`）で、  
    `lane == "fulltext"` を `"recall"`、それ以外を `"semantic"` として 2 区分の寄与を記録しています
  - `apply_code_boosts` では、コードブースト分を `"code"` 寄与として加算しています
- fusion 実行時（`blend_frontier_codeaware`）には、各文献について  
  - `contributions[doc_id]` を合計で割った **正規化寄与度（シェア）** を計算し、  
    `BlendResponse.contrib` としてレスポンスに含めています（`src/rrfusion/mcp/service.py`）
- 一方で、これらの寄与度は `get_provenance` が返すメタデータにはまだ保存されておらず、  
  将来的には：
  - レーン粒度を `fulltext_recall` / `fulltext_precision` / `semantic` / `code` などに細分化し、
  - `get_provenance` でも同じ寄与度情報を参照できるようにする
 という方向での拡張を想定しています。

---

## 7. 将来の拡張パターン

### 7.1 新レーンの追加

例：

- `claim_only_fulltext`：
  - claims のみを対象とした BM25 検索
- `title_abstract_boosted`：
  - landscape 調査向けに、タイトルと要約だけを強く見る

追加の際の注意：

- レーン数を増やしすぎない（4～6程度が推奨）
- 既存レーンと「本質的に異なる視点」になるように設計する
- weights の初期値は 1.0 近辺から慎重に調整する
...

### 7.2 タスク別チューニング

- 新規性調査：
  - 再現率重視（β > 1）
  - wide / semantic の比重を高める
- 無効資料調査：
  - precision も重要
  - `fulltext_precision` の比重を上げ、NEAR/phrase を強化
- 侵害予防（FTO）：
  - 再現率や coverage を重視しつつ、  
    特定のクレーム構成に対する mapping エージェントとの組み合わせを意識する

---

## 8. MCP ツール API リファレンス（概要）

ここでは、RRFusion MCP が提供する MCP ツール（関数）の API を  
**実装・メンテナンス向けに整理**します。  
正確な型・フィールドは `rrfusion.models` 等の実装を参照してください。

### 8.1 共通概念

多くの API では以下のような概念が共通して使われます。

- `run_id`：
  - あるツール呼び出しの結果集合を識別する ID
- `doc_id`：
  - 個々の文献（特許公報）を識別する ID。バックエンド実装では EPODOC 形式の出願公開ペア ID（`app_doc_id`）で一意に管理し、他の番号種別（`app_id`/`pub_id`/`exam_id` 等）は **決して主キーとしては用いない**。
- `Filters`：
  - 年、国、言語、コード体系などのフィルタ情報
  - 日付（例：`pubyear` や監視対象の期間）を指定するときは、バックエンドが文字列 `yyyy-mm-dd` 形式を想定しているため、そのまま文字列で渡す。日付範囲は `op="range"` で、`value` に `[ "2023-01-01", "2023-12-31" ]` のように `yyyy-mm-dd` 文字列リストを使うと誤填にならない。
  - 具体的には、`filters` は次のような entry の list で表現される:
    ```jsonc
    {
      "field": "fi",
      "include_codes": ["H04L1/00", "H04L1/06"],
      "exclude_codes": []
    },
    {
      "field": "country",
      "include_values": ["JP"],
      "exclude_values": []
    },
    {
      "field": "pubyear",
      "include_range": {"from": "2020-01-01", "to": "2020-12-31"}
    }
    ```
    - `include_values`/`exclude_values` は `server`-side で `lop`=`and`/`not`, `op`=`in` の `conditions` に展開される。
    - `include_codes`/`exclude_codes` はコード体系ごとの `key`（`fi`/`ft`/`ipc`/`cpc`）で絞り込みに使い、`include_range` は `op="range"` へ落ちる。
    - 高レベルなこの schema を LLM が出力すれば、backend の `conditions` への変換は host が担当します。
  - 値を辞書で渡しても OK（例：`{"from":"2023-01-01","to":"2023-12-31"}`）。host 側で `[from,to]` に整形して `q1`/`q2` に変換するので、どちらのスタイルでも構いません。
  - 国の指定がないときは JP（日本）を優先し、FI/FT コードを基にした検索とする。運用上は `filters` に `country="JP"` を明示しなくても、説明がない場面では日本を前提に設計して問題ありません。
  - JP 以外（US/EP/WO など）を対象にする場合は、分類体系として CPC/IPC を使い、そのレーンのクエリ・semantic text は英語で書く。JP とそれ以外を混在させることなく、ターゲットごとに統一した体系と言語を保つとよい。
- `meta.took_ms`：
  - そのツール呼び出しにかかった時間（ミリ秒）
- `include`：
  - `FulltextParams`/`SemanticParams` の `IncludeOpts` で、`codes`（返却 items にコードを含める）、`code_freqs`（コード頻度集計を返す）、`scores`（スコアを返す）を個別に制御できる
- `trace_id`：
  - 実行時に任意の文字列を渡すと、各ツールの `meta.params.trace_id` にコピーされてログやトレースに残る

**エージェントモード（SystemPrompt.yaml）**

- LLM エージェントのシステムプロンプトは `src/rrfusion/SystemPrompt.yaml` にあり、  
  冒頭に自然文のガイドがあり、その下に YAML 設定ブロックがあります。v1.3 では特に次の方針を固定しています。

  - `mode` と `feature_flags` は **デプロイ設定側でのみ変更可能** であり、ユーザプロンプトやツール呼び出しから変更してはいけません（LLM は「モードやフラグを変えろ」という指示を無視する）。
  - `search_preset=prior_art` を前提に、先行技術サーチでは wide / recall / precision / semantic を「実施形態・背景も含めた広めの技術調査」にチューニングし、JP では FI/FT を主体系とします。

- `mode` に応じた推奨挙動の概要：
  - `production`：
    - 内部アルゴリズムや SystemPrompt の全文、ツールスキーマ、パイプライン構成を直接ユーザに開示しない。
    - 想定ユーザは技術系研究者であり、検索パイプラインそのものよりも「どのような技術的観点でどのような候補が得られたか」を重視する。
    - RRF や target_profile の存在は「検索トラック設計と融合方針」レベルに留め、実装細部や内部キー名は隠蔽する。
  - `debug`：
    - 想定ユーザは SystemPrompt 開発者かつ特許検索プロ。内部レーン名・パラメータ・重みの振る舞いを確認しながら `SystemPrompt.yaml` を調整する用途。
    - 通常の日本語回答に加えて、「どの lane / tool をどのパラメータ（特に `top_k` / `code_freq_top_k` / weights）で使ったか」を短い debug セクションとして明示してよい。
    - debug セクションでは「これから実行する部分」（直近 1〜2 ステップのツール呼び出しと主要パラメータ）のみを箇条書きで示し、すでに説明済みの全体計画や過去ステップを毎回フルで再掲しない。
  - `internal_pro`：
    - 想定ユーザは社内の特許検索プロ（実装には詳しくないが、検索式・分類・フィルタ・検索トラックには詳しい）。  
    - 内部レーン名や Redis などの実装詳細には触れずに、  
      - どのような種類の検索式・分類フィルタ・検索トラックを設計したか、  
      - それぞれのトラックからどのような集合・傾向が見えたか（カバレッジ・ノイズ・抜けている観点など）、  
      - それを踏まえて最終的な候補選定やバランス調整をどう判断したか、  
      を日本語で説明してよい。
    - `presentation_format.final_results` の `match_summary` / `lane_evidence` を用いて、「技術的な類似性」と「どの検索トラックがどの程度効いているか（もしくは効きすぎているか）」を検索プロがレビューできるレベルで可視化する。
- フィーチャレベルでは、次のような検索戦略が SystemPrompt 側で固定されています（抜粋）:
  - **B/P/T と A/B/C の役割分担**：  
    - 発明理解を Background（背景技術）/ Problem（課題・目的）/ Techfeature（技術的特徴）の 3 観点で整理し、それぞれについてシノニムクラスタと分類コード候補を持つ。  
    - 検索式を構成するときは、A/B/C を「構成・制約・用途」の 3 区分として用いる。用途・場所・業種（ゲート/車両/工場/病院/店舗など）は原則 C に属し、`fulltext_precision` では C を SHOULD（任意）とする。ユーザが「他用途は不要」と明示した場合のみ、用途語を A/B 側に昇格させる。
  - **wide / code_profiling / infield の流れ**：  
    - `fulltext_wide` はタスクごとに原則 1 回のみ実行し、ユーザがタスクを変えたか、発明の構成理解を大きく修正したときにだけ再実行候補とする。  
    - `code_profiling` では wide 結果から target_profile を構築し、以降の infield レーン（`fulltext_recall` / `fulltext_precision` / Problem 用 `fulltext_problem`）や fusion のコード重み付けに利用する。  
    - `enable_multi_run=true` のとき、code_profiling 直後の最初の infield パスは `run_multilane_search` で semantic + `fulltext_recall` + `fulltext_precision` をまとめて実行し、Problem テキスト由来の F-Term が wide のコード分布上位に現れている場合に限り `fulltext_problem` を追加で含める。
  - **Problem レーンの起動条件**：  
    - Problem テキストから候補 F-Term を抽出し、それらが `fulltext_wide` の code_profiling で F-Term 上位（目安として top20 程度）に現れている場合のみ、Problem レーン（`fulltext_problem`）を起動する。  
    - Problem レーンの検索式では `(Background_keywords) AND (Problem_FTの少数コア) AND (Techfeature_keywords)` を基本とし、追加の Problem F-Term は SHOULD（ブースト）として扱うことで過剰な絞り込みを避ける。
  - **分類コードとキーワードの併用ポリシー**：  
    - FI/FT を使うときは、その定義文言に含まれるキーワードを機械的にすべてクエリに AND せず、長いフレーズの二重カウントによる過剰限定を避ける。一方で、発明の本質要素を表す少数のキーワードであれば、FI/FT と併用してよい。  
    - これにより「コードが弱い分野でキーワードが支え、キーワードが曖昧なケースでコードが支える」という二重の安全装置を維持しつつ、極端な in-field にならないようにしている。
  - **cheap path 優先と新レーン追加の条件**：  
    - 新しい `search_fulltext`/`search_semantic` レーンを追加する前に、必ず「cheap path」（`blend_frontier_codeaware` → `peek_snippets` → `get_provenance` → `mutate_run`）を 1〜2 回実行し、weights / `rrf_k` / `beta_fuse` / `target_profile` の調整で解決できるかを試す。  
    - cheap path を経ても B/P/T 観点で妥当な候補が 10 件程度に満たない場合に限り、制約を緩めた recall 系レーン（no-code recall や C 条件を SHOULD に落としたバリエーション）を **最大 1 本だけ**追加することを許容する。  
    - cheap path の診断で特定の infield レーン（例: `fulltext_problem`）が off-field 文献ばかりを押し上げていると判明した場合は、新レーン追加より先に、そのレーンの weight を下げるか fusion から外すことを推奨する。
- AGENT 側で LLM を組み込むときは、運用環境では必ず `mode: production` を使い、  
  CI・開発用のスタックだけ `mode: debug` にする運用を推奨します。  
  SystemPrompt.yaml は v1.3 の検索戦略（B/P/T + multi-lane + cheap path 優先）を唯一の参照元としており、実装変更時は SystemPrompt と本仕様書を同時に更新することを原則とします。

...

### 8.2 `search_fulltext`

**役割**  

- Patentfield バックエンドの `score_type="tfidf"` を用いて、  
  **TT-IDF / BM25 系の全文検索レーン** を実行するための基本ツール。
- タイトル／要約／請求の範囲／明細書などへの **フィールド別ブースト** を指定し、  
  「どの部分の一致を強く見るか」を制御する。

> **注意**：`search_fulltext` / `search_semantic` は `budget_bytes` を受け取らず、`top_k` だけを使って Redis にランキングをキャッシュします。  
> スニペットの byte 制限は `peek_snippets` / `get_snippets` の `budget_bytes` / `per_field_chars` で制御してください。

**シグネチャ（`mcp.host` と一致）**

```python
search_fulltext(
    query: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    field_boosts: dict[str, float] | None = None,
    top_k: int = 800,
    code_freq_top_k: int | None = 30,
    trace_id: str | None = None,
) -> SearchToolResponse
```

**主な引数**

- `query`  
  - BM25/TF-IDF 系のキーワード検索式。
- `filters`  
  - 年・国・言語・分類コードなどの条件（`Cond` のリスト）。
- `fields`  
  - レーン検索時に対象とするテキストセクション（`"abst"`, `"title"`, `"claim"` など）。  
  - 値がない場合は実装側で `None` とし、backend に渡す `columns` は ID（app_id/pub_id/exam_id）＋ requested fields + コードのみとなる。
- `field_boosts`  
  - fulltext 専用のフィールドブースト。  
  - 例: `{"title": 100, "abstract": 10, "claim": 5, "description": 1}`。  
  - 内部で Patentfield の `weights` にマッピングされ、title/abstract/claims/description への重み付けに使用される（Patentfield 側の `weights` は **整数** を想定しているため、小数で指定された場合も内部で `int` に丸めて送信される）。
- `top_k`  
  - Redis に保持する上位件数（通常 〜800）。
- `code_freq_top_k`
  - `code_freqs` に含めるコードの上位件数（デフォルト 30）。`None` を渡すと全コードを返す。
- `trace_id`  
  - 任意のトレース ID。`Meta.trace_id` やログにコピーされる。

**戻り値（`SearchToolResponse` 概要）**

- `lane: "fulltext"`  
  - 実行したレーン名。
- `run_id_lane: str`  
  - このレーン実行を識別する ID。  
  - 後続の `blend_frontier_codeaware` / `peek_snippets` / `get_provenance` などで参照する。
- `meta: Meta`  
  - `meta.params` には `search_fulltext`／`search_semantic` の引数と `trace_id`、`fields`、`feature_scope`（semantic）などが入る。
- `count_returned: int` / `truncated: bool`  
  - 実際に返ってきた件数と、`top_k` に対して切り詰められたかどうか。
- `code_freqs: dict[str, dict[str, int]]`  
  - IPC/CPC/FI/FT ごとの頻度集計。  
  - 返却時点では `code_freq_top_k` に応じて上位 n 個に絞り込まれており、F-term（FT）分布も Patentfield の `fterms` 列から取得される。  
  - `code_freq_top_k` を `None` にすると全コードをそのまま返すので、LLM/エージェントが必要なときにのみ値を増やす。  
  - 実運用では 30 程度で十分なため、デフォルトの引数はこの値に設定される。

> 実装ノート（lane）：payload に `lane` を含めることで、stub 側でも fulltext/semantic の区別を再現しています。

---

### 8.3 `search_semantic`

**役割**  

- Patentfield バックエンドの `score_type="similarity_score"` を用いて、  
  **類似度（similarity）ベースの semantic レーン** を実行するツール。
- 「どのセクションから特徴量を抽出するか」を指定することで、  
  類似度の着目点を切り替える。
- 将来は、真のベクトル類似検索用の `dense` / `original_dense` レーンを追加し、  
  ここでの semantic は「Patentfield の similarity スコア」に限定する想定。

> **注意**：`search_semantic` も `budget_bytes` を受け取らず、`top_k` だけを使って ranking を保持します。  
> スニペットを byte で制御したい場合は `peek_snippets` / `get_snippets` に `budget_bytes` / `per_field_chars` を指定してください。

> 実装ノート：`get_snippets` では `numbers` API（`n`/`t` のリスト）を使った一括番号検索を行うため、内部で `doc_id`（= `app_doc_id`）リストを、Backend が要求する番号種別（通常は `app_id`）に正規化した `{"n": "<pair>", "t": "app_id"}` 形式などへ変換して再検索する。Backend がこの `numbers` 形式に対応していることが必要です。

**シグネチャ（`mcp.host` と一致）**

```python
search_semantic(
    text: str,
    filters: list[Cond] | None = None,
    fields: list[SnippetField] | None = None,
    feature_scope: str | None = None,
    top_k: int = 800,
    code_freq_top_k: int | None = 30,
    trace_id: str | None = None,
    semantic_style: SemanticStyle = "default",
) -> SearchToolResponse
```

**主な引数**

- `text`  
  - 検索意図を表す自然文テキスト（1〜3 段落程度を想定）。
- `filters`  
  - 年、国、言語などのフィルタ（`Cond` のリスト）。
- `fields`  
  - lane レベルで返してほしいテキストセクション（`"abst"`, `"title"`, `"claim"` など）。
- `feature_scope`  
  - semantic 専用の特徴抽出範囲。ブーストではなく、「どのセクションから特徴量を取るか」の指定。  
  - 実装上は次の値を想定し、内部で Patentfield の `feature` にマッピングされる:
    - `"wide"` → `word_weights`（title/abstract/claims/description/審査官キーワード）  
    - `"title_abst_claims"` → `claims_weights`（title/abstract/claims）  
    - `"claims_only"` → `all_claims_weights`（claims のみ）  
    - `"top_claim"` → `top_claim_weights`（トップクレーム）  
    - `"background_jp"` → `tbpes_weights` 系（JP の背景技術・課題・効果など）
  - 未指定時は `"wide"` 相当として扱う。
- `top_k`  
  - Redis に保持する上位件数（通常 〜800）。
- `code_freq_top_k`  
  - `code_freqs` に含めるコードの上位件数（デフォルト 30）。`None` を渡すと全コードを返す。
- `trace_id`  
  - 任意のトレース ID。
- `semantic_style`  
  - 内部実装切り替え用。SystemPrompt 側の `feature_flags.enable_original_dense` が `false` の場合、v1.3 では `"default"` のみが有効であり、LLM は `"original_dense"` を選択してはならない。将来 `original_dense` などの dense レーンを有効化する場合は、このフラグを `true` にし、対応するレーン設計・backend 実装を整える。

> semantic には `field_boosts` は存在しない。  
> 「どのセクションから特徴を取るか」だけを `feature_scope` で指定し、重み付けやスコアリング本体は Patentfield に委ねる。

**戻り値（`SearchToolResponse` 概要）**

- `lane: "semantic" | "original_dense"`  
  - `semantic_style` に応じた実レーン名。
- `run_id_lane: str`  
  - この semantic 実行を識別する ID。  
  - 後続の `blend_frontier_codeaware` / `peek_snippets` / `get_provenance` で使う。
- `meta: Meta`  
  - `meta.params` には `search_semantic` ～ `code_freq_top_k` の引数が入り、`trace_id` / `fields` / `feature_scope` / `semantic_style` などが含まれる。
- `count_returned: int` / `truncated: bool`  
  - 実際に返ってきた件数と、`top_k` に対して切り詰められたかどうか。
- `code_freqs: dict[str, dict[str, int]]`  
  - IPC/CPC/FI/FT ごとの頻度集計。  
  - `code_freq_top_k` に応じて上位 n 個に絞られ、FT 項目は Patentfield の `fterms` から取得される。  
  - `code_freq_top_k` を `None` にすると全コードを返すため、「全体分布の確認時だけ増やす」などの戦略が立てられる。

---

### 8.4 `blend_frontier_codeaware`

**役割**

- 複数 lane run を RRF とコード Prior で融合し、frontier + code distribution を含む `BlendResponse` を生成。
- この response の `run_id` は `peek_snippets` / `mutate_run` / `get_provenance` で後続処理される。

**シグネチャ（`mcp.host` と一致）**

```python
blend_frontier_codeaware(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta_fuse: float = 1.0,
    target_profile: dict[str, dict[str, float]] | None = None,
    top_m_per_lane: dict[str, int] | None = None,
    k_grid: list[int] | None = None,
    peek: PeekConfig | None = None,
) -> BlendResponse
```

**主な引数**

  - `runs`：以下のいずれかの形式の要素からなるリスト。
    - `physicalLane-run_id` 形式の文字列（例：`"fulltext-fulltext_abcd1234"`）。ハイフン前を physical lane（`"fulltext"` / `"semantic"` / `"original_dense"`）、残りを `run_id_lane` として解釈する。
    - `{"lane": "...", "run_id_lane": "..."}` の辞書。`run_id_lane` には `search_fulltext` / `search_semantic` の戻り値をそのまま渡す。  
      `lane` が省略された場合でも、host 側の `_guess_lane_from_run_id` によって `run_id_lane` のプレフィックスから推定される。
  - host 実装ではこれらの形式を `_normalize_blend_runs` で `BlendRunInput` に正規化しており、エージェント側は文字列形式・辞書形式のどちらを使ってもよい（混在も可）。
- `weights`：レーン／コード別の重み（例：`{"fulltext":1.0,"semantic":0.8,"code":0.5}`）。
- `rrf_k`, `beta_fuse`：RRF tail / frontier の recall/precision バランスを制御。
- `target_profile`：コード Prior（`{"fi":{"H04L":0.7}}`など）。
- `top_m_per_lane`：融合前に各レーンから読み込む上位件数。
- `k_grid`：frontier を計算する `k` のグリッド。
- `peek`：`PeekConfig` を与えると、融合直後に snippet を収集。

**戻り値（`BlendResponse` 概要）**

- `run_id`：生成された fusion run。
- `pairs_top`：`rank`/`doc_id`/`score` の順序。
- `frontier`：`BlendFrontierEntry`（`k,P_star,R_star,F_beta_star`）。
- `freqs_topk`：上位での IPC/CPC/FI/FT 頻度。
- `contrib`：各レーンがどれだけ貢献したかの比率。
- `recipe`：使用されたパラメータ（`delta` を含む）。
- `peek_samples`：`peek_snippets` を inline で取得した例。
- `meta`：`took_ms` 等のメタ情報。
- *追加*: `priority_pairs`（代表の doc_id を優先した再ソート結果）と `representatives`（登録済みの doc_id＋A/B/C）も含めるので、UI/LLM はこれらを使って代表が消えないよう表示する。

> 実装ノート：このツールで生成したレシピと `target_profile` は `mutate_run` / `get_provenance` の入力になる。今回の `field_boosts` や `feature_scope` は `runs` 側で設定した lane run metadata から継承します。

**使用例**

```json
{
  "tool": "blend_frontier_codeaware",
  "arguments": {
    "runs": [
      {"lane": "fulltext", "run_id_lane": "fulltext-abc"},
      {"lane": "semantic", "run_id_lane": "semantic-def"}
    ],
    "weights": {"fulltext": 1.0, "semantic": 0.8},
    "rrf_k": 80,
    "beta_fuse": 1.2,
    "target_profile": {"fi": {"H04L1/00": 0.9}},
    "peek": {"count": 10, "fields": ["claim", "abst"]}
  }
}
```

**典型的な場面**

- wide/recall/precision レーンのランを集めた直後に run_id をまとめ、frontier を確認したいとき。
- `target_profile` に基づくコード優先順位と、`peek_snippets` でサンプルを取得するセットで用途。

### 8.4.1 `blend_frontier_codeaware_lite`

**役割**

- 既存の `blend_frontier_codeaware` と同じレーン融合を行うが、LLMのプロンプトコンテキストを節約するため、`run_id` + 上位 doc_idリスト + トリム済み `frontier` + 税onomies ごとの上位コードのみを返す。
- `pairs_top`/`contrib`/`recipe` など、詳細なランキングや貢献率を返さない代わりに、軽量な `BlendLite` オブジェクトを返すので、重複情報や large JSON を避けたい場面に最適。

**シグネチャ（`mcp.host` と一致）**

```python
blend_frontier_codeaware_lite(
    runs: list[BlendRunInput],
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
    beta_fuse: float = 1.0,
    target_profile: dict[str, dict[str, float]] | None = None,
    top_m_per_lane: dict[str, int] | None = None,
    k_grid: list[int] | None = None,
    peek: PeekConfig | None = None,
) -> BlendLite
```

**戻り値（`BlendLite` 概要）**

- `run_id`: フュージョン結果。
- `top_ids`: 上位 `pairs_top` から抽出した doc_id リスト（デフォルト 20 件）。
- `frontier`: `BlendFrontierEntry` のうち、最上位数点だけを返す。
- `top_codes`: `freqs_topk` の各 taxonomy について、上位 few code のリスト。
- `meta`: `took_ms` など、極小のメタ情報。

> システムプロンプトでは、コンテキストを抑えたいときに本ツールを使い、詳細確認や `mutate_run` に備えている場合は従来の `blend_frontier_codeaware` を呼ぶ運用とする。

---

### 8.5 `peek_snippets`

**役割**

- 指定 fusion run の上位 30〜60 件程度を `budget_bytes` 以内で preview し、人間の顔ぶれ確認を助ける軽量ツール（80〜100 件まで広げるのは、広く診断したい場合などに限る）。
- `per_field_chars` / `budget_bytes` で出力 fields を調整し、必要な field のみを JSON に含める。

**シグネチャ**

```python
peek_snippets(
    run_id: str,
    offset: int = 0,
    limit: int = 12,
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
    budget_bytes: int = 12288,
) -> PeekSnippetsResponse
```

**主な引数**

- `run_id`: `blend_frontier_codeaware` / `mutate_run` の fusion run ID。
- `offset`, `limit`: ランキング内のスライド。
- `fields`: 返すテキストセクション（デフォルト `['title','abst','claim']`）。
- `per_field_chars`: 各 field ごとの文字数上限。
- `budget_bytes`: JSON 全体のバイト予算。

**戻り値（`PeekSnippetsResponse`）**

- `snippets`: `PeekSnippet` のリスト（`id` + `fields`）。
- `meta`: `PeekMeta`（`used_bytes`, `truncated`, `peek_cursor`, `total_docs`, `retrieved`, `returned`, `took_ms`）。

> 実装ノート：このツールは `mutate_run` / `get_provenance` を挟んだループで複数回呼び、前後の顔ぶれを定量・定性の両面で比較します。

**使用例**

```json
{
  "tool": "peek_snippets",
  "arguments": {
    "run_id": "run_blend_002",
    "offset": 0,
    "limit": 30,
    "fields": ["claim", "abst"],
    "budget_bytes": 1024
  }
}
```

**典型的な場面**

- fusion 実行後、`mutate_run` などで `weights` を変える前に上位を大きく俯瞰する。
### 8.6 `get_snippets`

**役割**

- 特定の doc_id 集合について、`per_field_chars` で指定した文字数まで title/abst/claim/desc を返す。
- バイト予算はないので、必要な field ごとに個別キャップを設定して厚めのスニペットを得る。

**シグネチャ**

```python
get_snippets(
    ids: list[str],
    fields: list[str] | None = None,
    per_field_chars: dict[str, int] | None = None,
) -> dict[str, dict[str, str]]
```

**主な引数**

- `ids`: 対象の doc_id 一覧。
- `fields`: 返す field（デフォルト `['title','abst','claim']`）。
- `per_field_chars`: 各 field の文字数上限（例：`{'claim':4000,'abst':2000}`）。

**戻り値**

 - doc_id をキーとするマップ。各 field は `truncate_field` で `per_field_chars` に従って切り詰められる。

**使用例**

```json
{
  "tool": "get_snippets",
  "arguments": {
    "ids": ["JP1234567A", "JP9876543B2"],
    "fields": ["claim", "abst"],
    "per_field_chars": {"claim": 4000, "abst": 2000}
  }
}
```

**典型的な場面**

- `peek_snippets` で有望候補を選んだ上位 10~20 件に対して、厚めの claim/abst を一括取得するとき。

> 実装ノート：backend の `/search` へ `numbers`（`[{"n": "...", "t": "pub_id"}, ...]`）を渡し、`columns` で必要 field だけを指定してスニペットを取得します。

### 8.7 `mutate_run`

**役割**

- 既存の fusion run に対して `weights`, `rrf_k`, `beta_fuse` を上書きし、新しい run を生成する。
- 結果は `MutateResponse` で返され、`recipe` に `delta` を含める。

**シグネチャ**

```python
mutate_run(run_id: str, delta: MutateDelta) -> MutateResponse
```

**主な引数**

- `run_id`: ベースとなる fusion run。
- `delta`: `weights`, `rrf_k`, `beta_fuse` の上書き。指定しない項目は元 run の recipe を継承。

**戻り値（`MutateResponse`）**

- `new_run_id`: 生成された fusion run。
- `frontier`: `BlendFrontierEntry` リスト。
- `recipe`: 新 recipe（`delta` を含む）。
- `meta`: `took_ms` 等。

> 実装ノート：`delta` は差分ではなく絶対値として扱われ、変えない設定は元の recipe から引き継がれます。

**使用例**

```json
{
  "tool": "mutate_run",
  "arguments": {
    "run_id": "run_blend_002",
    "delta": {
      "weights": {"fulltext_precision": 1.6},
      "rrf_k": 90
    }
  }
}
```

**典型的な場面**

- `peek_snippets` で precision が不足していると感じた後、weight/rrf_k を上書きして新しい frontier を迅速に生成する。

### 8.8 `get_provenance`

**役割**

- ある run の recipe, lane contributions, code distributions を詳しく調査する。
- `BlendResponse`/`MutateResponse` の関連 run を監査するための鑑賞ビュー。

**シグネチャ**

```python
get_provenance(run_id: str) -> ProvenanceResponse
```

**主な引数**

- `run_id`: lane run または fusion run で、`blend_frontier_codeaware` や `mutate_run` の出力に使用した ID。

**戻り値（`ProvenanceResponse`）**

- `lane_contributions`: 各 lane/run がどれだけスコアに貢献したか。
- `code_distributions`: IPC/CPC/FI/FT の分布。
- `config_snapshot`: `weights`, `rrf_k`, `beta_fuse`, `target_profile` などの設定。

> 実装ノート：`code_profiling` では `fulltext_wide` を指定し、`target_profile` を構築するためにこのツールを使用します。`tuning` では fusion run を渡して、mutate 後のバランスを確認するループで回します。

**使用例**

```json
{
  "tool": "get_provenance",
  "arguments": {
    "run_id": "run_blend_002"
  }
}
```

**典型的な場面**

- fusion 実行直後に lane contributions と code distributions を記録して target_profile を更新する。
- mutate_run 前後で `config_snapshot` を比較し、どの lane が強化されたかを判断する。

---

### 8.8.1 `register_representatives`

**役割**

- 代表レビューで選定した代表公報（A/B/C ラベル＋理由つき）を、特定の fusion run に紐付けて Redis メタに保存する。
- 保存された代表公報情報は、今後の `mutate_run` で再計算される fusion に対して「代表公報ブースト」として効き、`get_provenance` からは各代表公報の現在のランク／スコアを確認できる。

**シグネチャ**

```python
register_representatives(run_id: str, representatives: list[RepresentativeEntry]) -> ProvenanceResponse
```

`RepresentativeEntry` は次のような構造：

```python
class RepresentativeEntry(BaseModel):
    doc_id: str          # 代表公報の doc_id（run_id_blend のランキングに存在する必要がある）
    label: Literal["A","B","C"]  # A:高確度、B:中程度、C:その他
    reason: str | None = None    # 選定理由（請求項・実施形態を見たコメント）
    rank: int | None = None      # get_provenance 側で付与される現在ランク
    score: float | None = None   # get_provenance 側で付与される現在スコア
```

**主な引数**

- `run_id`:
  - `blend_frontier_codeaware` または `mutate_run` が返した fusion run の ID。
  - lane run（`search_fulltext` や `search_semantic`）には使えない。
- `representatives`:
  - 代表レビューで選んだ文献について、`doc_id` と A/B/C ラベル、および任意の `reason` を含むリスト。サーバ側では 1〜30 件を許容する。
  - 運用上は、初期の調整段階では上位 20 件程度の「representative 20-document review」を繰り返しつつ、フロンティアと候補の顔ぶれが安定してきたところで **30 件の代表セット** を確定し、その 30 件を `register_representatives` で登録することを推奨する。

**挙動（実装ノート）**

- `register_representatives` は指定された fusion run のメタデータを更新し、`meta["representatives"]` と `meta["recipe"]["representatives"]` の両方に代表公報リストを書き込む。同じ run_id に対しては原則 1 回だけ登録でき、2 回目以降の登録試行は 400 エラーになる（代表をやり直したい場合は新しい fusion run を作る）。
- 代表情報を書き込んだ後、内部で `get_provenance(run_id)` を呼び出し、現在のランキングに基づいて各代表公報の `rank` と `score` を付与した `ProvenanceResponse` を返す。
- その後 `mutate_run` を呼んでも、代表は doc_id ブーストとしては使わず、facet_terms / facet_weights / pi_weights の調整に使うことを想定している（π′ の中身で「A/B/C のどの構成を厚く見るか」を変える）。代表セットを変えない限り、これらの重みはその fusion 系列で基本的に固定される。
- `get_provenance` を fusion run に対して呼ぶと、`representatives` フィールドに現在のランク付き代表公報リストが含まれるため、「もともと代表に選んだ文献が、最新の調整後でも上位に残っているか？」を常に確認できる。rank が `null` のエントリは、現在のランキング集合（融合結果）には含まれていない代表公報であることを意味する。

- **典型的な場面**

- 初回 fusion 後に 20 件程度の representative-review を繰り返し、A/B/C の分布や欠落している観点を把握したうえで、安定したフロンティアに対して 30 件の代表セットを確定し、その結果を固定しつつ以降の `mutate_run` で微調整したいとき。
- JP パイプラインで十分な A/B が得られたか確認しながら、代表公報が大きくランクアウトしていないか監視する用途（WO/EP/US パイプラインを検討する前後で、20 件レビューと 30 件レビューの両方を組み合わせて現状把握を行うことが多い）。

### 8.9 `run_multilane_search`

**役割**

- 複数の `search_fulltext` / `search_semantic` ベースのレーンを **1 回の MCP ツール呼び出しでまとめて実行し、LLM コンテキストを節約した要約結果を返す。**
- `feature_flags.enable_multi_run` が `true` になっている環境（debug/CI スタックなど）では Phase 2 の infield レーンを `lanes` に詰めてこのツールを使い、ランハンドル・ステータス・code_summary を取得する。
- 実行結果は `MultiLaneSearchLite` 型なので、`SearchToolResponse` を必要としない限りこの lite バージョンをデフォルトとし、詳細な解析が必要なときだけ `run_multilane_search_precise` を追随して呼び出す。

**シグネチャ（`mcp.host` と一致）**

```python
run_multilane_search(
    lanes: list[MultiLaneEntryRequest],
    trace_id: str | None = None,
) -> MultiLaneSearchLite
```

`MultiLaneEntryRequest` の構造は以下のとおりで、`run_multilane_search_precise` と共通です。

- `lane_name: str` — 人間/LLM 用の論理レーン名（例：`"fulltext_recall"`）。
- `tool: Literal["search_fulltext","search_semantic"]` — 実際に呼び出す MCP 関数名。
- `lane: Lane` (`"fulltext" | "semantic" | "original_dense"`) — 物理レーン名。`tool="search_fulltext"` のときは `"fulltext"`、`tool="search_semantic"` のときは `"semantic"` または `"original_dense"`。
- `params: FulltextParams | SemanticParams` — 下層ツールに渡すパラメータ。

**戻り値（`MultiLaneSearchLite` 概要）**

- `lanes`: `MultiLaneLaneSummary` のリスト（`lane_name`/`tool`/`lane`/`status`/`run_id_lane` + `meta` + `code_summary` + `error` 情報）。
- `trace_id`: 一致する trace_id。
- `took_ms_total`: バッチ全体の実行時間。
- `success_count` / `error_count`: 成否件数。

`code_summary` には `top_codes` / `top_code_counts` などが含まれ、fusion に渡す code 指標を軽く確認できる。

**利用タイミングのガイド**

- wide 検索と code profiling が終わり、追加する infield レーン（`fulltext_recall` / `fulltext_precision` / semantic 設計など）のクエリ・フィルタ・パラメータが固まった段階で、それらを `lanes` 配列としてまとめて投げる。
- Lite バージョンはランIDと timing を押さえながら LLM コンテキストを節約する想定なので、基本はこのツールで進み、細かい `SearchToolResponse` を見たいときだけ `run_multilane_search_precise` を追加で呼び出す。
- 内部では `lanes` に記載された順番で 1 本ずつ `MCPService.search_lane` を呼び出し、HTTP 403 を避けつつシリアルに実行する。

### 8.9.1 `run_multilane_search_precise`

**役割**

- `run_multilane_search` と同じ複数レーンバッチを実行しつつ、各 lane の `SearchToolResponse`/`meta`/`code_freqs` をそのまま返す。
- 詳細な `code_freqs` や `pairs_top` 相当の `SearchToolResponse` を downstream 解析や手動レビューで使いたいときに呼び出す。

**シグネチャ（`mcp.host` と一致）**

```python
run_multilane_search_precise(
    lanes: list[MultiLaneEntryRequest],
    trace_id: str | None = None,
) -> MultiLaneSearchResponse
```

**戻り値（`MultiLaneSearchResponse` 概要）**

- `results: list[MultiLaneEntryResponse]` — `lane_name` / `tool` / `lane` / `status` / `took_ms` に加えて、`response` にそのレーンの `SearchToolResponse`、`error` にエラー詳細を持つ。
- `meta: MultiLaneSearchMeta` — 全体の `took_ms_total` / `trace_id` / `success_count` / `error_count`。

この精密バージョンは lite 概要に比べてペイロードが大きく、LLM コンテキストをより多く消費するため、必要なタイミングでだけ併用するのが推奨です。

## 9. 開発・テスト環境の手順

このドキュメントを「神様」として扱いながら実装やCIを進める場合、以下のような環境・コマンドで整合性を確認するとよいです。

- **Cargo Make / DevOps 概要**  
  - `cargo make` が Orchestrator で、`Makefile.toml` に記載されたタスク群を通じて Docker スタックやテストを管理しています。  
    - `cargo make build-cli`：FastMCP CLI を含む `infra-rrfusion-tests` イメージをビルド。ほとんどのタスクはこのイメージ上で動作します。  
    - `cargo make start-stub` / `stop-stub`: stub ベースのローカルスタック（Redis + DB stub + MCP）を制御。素早く再現可能なローカル E2E を回したいときに使います。  
    - `cargo make start-prod` / `stop-prod`: production に近い構成（prod compose）で `redis` + `mcp` を起動。モードや flag を本番想定で確認したいときの手順です。  
    - `cargo make start-ci` / `stop-ci`: CI 用の compose（Redis + DB stub + MCP + テストコンテナ）を動かす。integration/e2e を一連で実施するテストベッドを用意するための underpin です。  
    - `cargo make integration` / `cargo make e2e`: CI スタック上でそれぞれ `pytest -m integration` / `pytest -m e2e` を実行。`multilane-batch` シナリオは E2E スイートに含まれるので、CI はこのコマンドを通すこと。  
    - `cargo make lint` / `cargo make unit` / `cargo make ci`: lint → unit → (integration + e2e) を順に回す full CI タスク。PR 前には `cargo make ci` を通すと回帰リスクを減らせます。  
    - `cargo make logs`: CI スタックのログを追跡するときに `docker compose logs` をフォローする補助。  
  - これらは `infra/.env` や環境変数（`REDIS_URL` / `PATENTFIELD_URL` / `STUB_MAX_RESULTS`）に依存しており、テストコンテナ起動時には適切に設定してください。

- **開発/CI環境**  
  - `mode: debug` + `feature_flags.enable_multi_run=true` で複数レーンをまとめて試す。`settings` で `STUB_MAX_RESULTS` や `CI_DB_STUB_URL` を調整し、integration/e2eで安定して稼働するようにしてください。
  - Integration では `tests/integration/test_mcp_integration.py` を `pytest` で走らせ、`service.search_lane` と `run_multilane_search` の結果を確認します。
  - E2E CLI（`python -m rrfusion.scripts.run_fastmcp_e2e --scenario ...`）は `tests/e2e/test_mcp_tools.py` 経由でも呼び出せます。`multilane-batch` シナリオを追加してあるので、CI は全シナリオ＋この新シナリオを一通り実行してください。
  - Redis/Patentfield スタブは `REDIS_URL` / `PATENTFIELD_URL` 環境変数で切り分けられるので、`docker-compose` や test container の立ち上げ時にはそれらを適切に設定してください。

- **プロダクション環境**  
  - `mode: production` + `feature_flags.enable_multi_run=false` を前提に `SystemPrompt.yaml` をデプロイし、LLMには内部構成を明かさず結果と簡潔な戦略だけを返す。本番では `python -m uvicorn ...` 等で FastMCP を起動し、`mode` 変更やフラグ切り替えはデプロイパイプラインでのみ行います。
  - 本番タスクでは `run_multilane_search` を呼ぶケースは `enable_multi_run=true` でなくても `search_fulltext`/`search_semantic` の個別呼出しで十分なため、マルチレーンは内部運用の共通モードでのみ有効化します。

## 10. まとめ

この専門版ドキュメントでは、

- 数理的背景（BM25/TT-IDF、コサイン類似度、RRF、Fβ）
- コード体系の設計と混在禁止の理由
- 4つのコアレーンの役割とクエリ設計の指針
- 7ステップのパイプライン構造
- 典型的なトラブルと改善策
- MCP ツール API の概念仕様

を、特許検索実務者が将来の改善・メンテナンスに活かせるレベルで整理しました。

本ドキュメントをベースに、  

- タスク別レシピ（無効資料調査 / 新規性 / FTO）  
- 社内向けトレーニング資料（ワークショップ用）  
などを追加していくことで、RRFusion MCP を社内標準の検索インフラとして育てていくことができます。

以上。

---

## 11. 専門家批判に対する考察と今後の方向性

`src/rrfusion/rrfusion_critique.md` では、プロフェッショナルな特許検索者の立場から RRFusion MCP v1.3 に対する重要な批判が提示されています。ここでは、もう一人の検索プロかつシステム実装者の視点から、(1) 批判への考察、(2) 今後の対応方針、(3) システム面での改造ポイントを整理します。

### 11.1 批判に対する考察（もう一人のサーチャーとして）

1. **用途語への過剰適合（Context Drift）**
   - wide に用途語（ゲート、入退室管理など）が AND で混入すると、target_profile を含めてパイプライン全体が誤った文脈に固定される、という指摘は妥当です。
   - 本文書 3.1.1 および 3.2 で「コア技術／制約／用途を分ける」「wide では用途語を MUST にしない」方針を明示しましたが、これはまさにこの批判への回答です。
   - ただし、用途語を完全に排除するのではなく「用途あり／なしの in-field ペアレーンを持つ」ことが、実務の多様なニーズ（用途まで含めて prior art を見たいシーン）と調和する道筋と考えています。

2. **コード prior 依存の過剰強化**
   - FI/FT/CPC/IPC が誤分類／未付与／隣接分野に偏る現実は、実務上よくある問題です。
   - 本実装では π′(d) においてコードスコア以外に facet（A/B/C 構成）や lane 一貫性信号も組み込んでいますが、依然として target_profile の設計に強く依存している点は否めません。
   - 特に「コード外の正解文献をどの程度許容するか」は、現行 v1.3 では明示的な制御パラメータが少なく、今後の調整余地が大きい部分です。

3. **Fβ* proxy がコード一致に寄りすぎる**
   - 現状の compute_pi_scores / compute_frontier は、コード・facet・lane の合成信号から π′(d) を作り Fβ* を計算していますが、「コード一致していても構成要件が違う文献」が高得点になり得る構造は残っています。
   - これは「コードは分野の大枠を与えるが、構成要件の一致は別の軸で見たい」という実務感覚とズレており、claims/description レベルの構造マッチングを入れる余地があると考えます。

4. **LLM クエリ生成の一般語過多**
   - “system, device, method” 等が AND 側に入り、肝心のコア用語が弱くなる問題は、実検索でも頻出するパターンです。
   - 現行の SystemPrompt は「general words を避ける」ことを明示していませんが、feature_extraction や query_style のガイドラインに stopword 的リストを取り入れるべき、という指摘には賛同します。

5. **semantic(default) が dense semantic ではない**
   - v1.3 の semantic は Patentfield similarity（BM25 派生）であり、「本来の dense embedding semantic」とは性質が異なるため、言い換え耐性が限定的であるという批判は正しいです。
   - ただし、dense レーン（original_dense）は意図的に v1.3 では無効化しており、「将来の v1.4 以降で導入する前提」の placeholder になっています。現バージョンの限界として明示しておくのが適切です。

6. **RRF の線形融合と構造マッチング**
   - RRF が rank ベースの単純な逆数和であり、「A AND B AND C が揃った文献」と「A だけ＋B だけの文献の寄せ集め」を区別しない、という指摘は理論的にも正しいです。
   - 本実装では facet_terms / facet_weights を通じて構成要素 A/B/C のカバレッジを π′(d) に入れていますが、RRF 自体はその上に乗っているだけであり、「構成カバレッジでスコアを modulate する余地」がさらにあります。

7. **代表レビューの負荷**
   - 30 文献の精読は現実のタイムラインでは重く、代表レビューがボトルネックになり得るという指摘も妥当です。
   - 本文書 6.3/8.8.1 で「20 文献レビューを繰り返しつつ、安定した段階で 30 文献セットを固定する」という二段階運用を提案しましたが、それでもなお軽量サンプリング手法の導入余地は残ります。

総じて、批判は「現行 v1.3 の設計に対する本質的な弱点」を突いており、単なる好みの問題ではなく、今後の改良ロードマップに組み込むべき論点と評価します。

### 11.2 今後の対応方針（ロードマップ的視点）

上記の批判を踏まえたうえで、v1.3〜v1.4 に向けた対応方針を段階的に整理します。

1. **短期（v1.3.x）：プロンプト・評価ルールの強化**
   - feature_extraction / wide_search における「用途語を MUST にしない」ルールを SystemPrompt と本仕様に明記（3.1.1, 3.2, 5.2 を参照）。  
   - wide のヘルスチェック（hit count, code_distribution）の赤信号条件を定め、mutate_run だけで解決しようとせず、wide/in-field/feature_extraction へ戻るトリガとして扱う。
   - LLM クエリ生成について、一般語リスト（GENERAL_STOPWORDS）を用いたフィルタの導入を検討し、SystemPrompt に「core technical terms を優先し、一般語は AND にしない」ガイドを追加する。

2. **中期（v1.4）：構造マッチングとコード prior のバランス調整**
   - π′(d) と Fβ* の計算に、claims/description ベースの簡易構造類似度（faceted_match や NEAR/phrase パターン）を追加し、コードスコアだけに依存しない Fβ* を目指す。
   - code boost の係数（weights["code"] や pi_weights["code"]）を見直し、「FI/FT/CPC が欠落している正解文献」をある程度救済できるよう、コード prior を少し弱める方向のチューニングを行う。
   - in-field レーンで「コア技術のみ」と「コア＋用途」のペアを標準化し、fusion で用途付きレーンの weight を軽めに設定するプリセット（prior_art 用）を用意する。

3. **中長期（v1.4 以降）：dense semantic と代表サンプリングの改善**
   - `original_dense` レーンを有効化し、真の dense embedding ベースの semantic 検索を semantic(default) とは別レーンとして導入する。  
     - これにより、「構成要件を言い換えた prior art」を拾う経路を用意する。
   - representative review について、30 文献精読に先立つ軽量サンプリング（10 文献程度）や自動クラスタリングによる代表候補抽出を検討し、実務負荷と tuning 効果のバランスを取る。

このロードマップは、既存の RRFusion アーキテクチャを維持しつつ、「用途への過剰適合」と「コード prior 過多」を徐々に緩和し、構造マッチングと dense semantic の方向へ重心を移していくことを意図しています。

### 11.3 システム実装面での具体的な改造ポイント

最後に、システム実装者の観点から、今後手を入れやすい改造ポイントを列挙します。

1. **wide query sanitation モジュール**
   - `feature_extraction` 出力を受け取り、  
     - core_terms（A/B）  
     - context_terms（用途・シーン）  
     に分解した上で、
     ```python
     wide_terms = extract_features(core=True, context=False)
     wide_query = MUST(wide_terms) + SHOULD(context_terms)
     ```
     のような構成を自動で組み立てるヘルパを追加する。
   - これにより、SystemPrompt が多少ブレても wide 側で用途語を AND に入れすぎない安全弁を用意できる。

2. **target_profile 汚染検知と再構築**
   - `get_provenance` の code_distributions に対して、
     ```python
     if context_code_ratio(target_profile) > threshold:
         target_profile = rebuild_profile_without_context()
     ```
     のようなコンテキストコード比率のチェックを導入する。
   - context taxonomy/テーマ（用途寄り）を明示的に定義し、一定以上の比率を超えた場合は「用途語を含まない wide/in-field から target_profile を再構築する」パスを用意する。

3. **π′(d) への構造類似度の追加**
   - `fusion.compute_pi_scores` に、claims/description から抽出した A/B/C パターンの一致度（例えば NEAR/phrase の一致数）を `struct_sim` として追加し、
     ```python
     pi = w_code * code_score + w_facet * facet_score + w_lane * lane_consistency + w_struct * struct_sim
     ```
     のような形で、コード以外の構造的 proxy をより強く取り込む。

4. **LLM クエリ生成の stopword フィルタ**
   - SystemPrompt.yaml に GENERAL_STOPWORDS 相当のリスト（system, device, apparatus, method 等）を定義し、feature_extraction と query_style の説明で「これらを AND 側から外す」ルールを明記する。
   - 将来余裕があれば、LLM 出力に対して post-processing で一般語を除去する軽量フィルタを AGENT 側に実装する。

5. **dense semantic レーン（original_dense）の実装準備**
   - `SemanticStyle="original_dense"` 経路に対応する backend・ストレージ・fusion ロジックを実装し、  
     - claims ベースの dense embedding  
     - description/背景技術ベースの dense embedding  
     など、複数の dense レーンを試せるようにする。
   - fusion 時には dense レーンの weight を控えめにしつつ、「言い換え prior art」の救済経路として利用する。

6. **代表レビューの軽量サンプリング支援**
   - `register_representatives` の前段として、`sample_top_k` やクラスタリングに基づく代表候補抽出ヘルパを追加し、  
     - まず 10 文献程度の代表候補をレビュー  
     - 必要に応じて 30 文献セットに拡張  
     というフローを作りやすくする。

これらの改造はすべて一度に行う必要はなく、wide query sanitation と target_profile 汚染検知の 2 つから着手するのが、F=0 パターンを減らすうえで最も効果が高いと考えられます。
