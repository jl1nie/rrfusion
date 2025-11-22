multirunspec.md

#やりたいこと
フェーズ1（wide＋code_profiling）までは今のシリアル＆LLM思考を維持
フェーズ2（semantic/recall/precision…）は
LLMで全部設計してから

MCPのマルチレーンツールに丸投げ

マルチレーンツール内は403を避けるためにシリアル実行でもOK
それでも「LLMの考える回数」が減るので全体は速くなる

# 具体例
## リクエスト
```json
{
  "lanes": [
    {
      "lane_name": "wide_fulltext",
      "tool": "search_fulltext",
      "lane": "fulltext",        // 既存 Lane 型と整合
      "params": {
        "query": "...",
        "top_k": 400,
        "filters": [],
        "fields": ["title", "abst", "claim"]
      }
    },
    {
      "lane_name": "core_semantic",
      "tool": "search_semantic",
      "lane": "semantic",
      "params": {
        "text": "...",
        "top_k": 300,
        "scope": "wide"
      }
    },
    {
      "lane_name": "recall_fulltext",
      "tool": "search_fulltext",
      "lane": "fulltext",
      "params": {
        "query": "...",
        "top_k": 600
      }
    }
  ],
  "trace_id": "rrf-2025-001"
}
```
lane_name: 人間／LLM が意味を分かりやすくするためのラベル
（wide_fulltext, precision_claims, sharp_claims_jp みたいな）

tool: 実際に叩く MCP 関数名（今は search_fulltext / search_semantic の想定）

lane: 既存の Lane = Literal["fulltext","semantic","original_dense"]
→ Fusion や Meta 側と揃えるため

params: そのツールに渡す 元のパラメータ（FulltextParams / SemanticParams 相当）

## レスポンス
```json
{
  "results": [
    {
      "lane_name": "wide_fulltext",
      "tool": "search_fulltext",
      "lane": "fulltext",
      "response": {
        "lane": "fulltext",
        "run_id_lane": "run_ftwide_001",
        "meta": { "top_k": 400, "took_ms": 28700, "params": {...} },
        "count_returned": 400,
        "truncated": false,
        "code_freqs": { ... },
        "cursor": null
      }
    },
    {
      "lane_name": "core_semantic",
      "tool": "search_semantic",
      "lane": "semantic",
      "response": {
        "lane": "semantic",
        "run_id_lane": "run_sem_001",
        "meta": { "top_k": 300, "took_ms": 29500, "params": {...} },
        "count_returned": 300,
        "truncated": false,
        "code_freqs": null,
        "cursor": null
      }
    },
    {
      "lane_name": "recall_fulltext",
      "tool": "search_fulltext",
      "lane": "fulltext",
      "response": {
        "lane": "fulltext",
        "run_id_lane": "run_ftrec_001",
        "meta": { "top_k": 600, "took_ms": 31000, "params": {...} },
        "count_returned": 600,
        "truncated": true,
        "code_freqs": {...},
        "cursor": "..."
      }
    }
  ],
  "meta": {
    "took_ms_total": 91000,
    "trace_id": "rrf-2025-001"
  }
}
```
##Pydanticモデル案
```pyhton
# models.py の末尾あたりに追加

from typing import Literal

# どの MCP 関数を許すか（まずは search 系だけ）
MultiLaneTool = Literal["search_fulltext", "search_semantic"]


class MultiLaneEntryRequest(BaseModel):
    """
    One logical lane execution inside a multi-lane batch.

    lane_name: human/LLM friendly name such as "wide_fulltext" or "precision_claims".
    tool: which MCP function to call (currently search_fulltext | search_semantic).
    lane: underlying Lane type used for fusion/meta ("fulltext" | "semantic" | "original_dense").
    params: request parameters for the underlying tool.
            For search_fulltext: FulltextParams
            For search_semantic: SemanticParams
    """

    lane_name: str = Field(
        description="Logical lane name, e.g. 'wide_fulltext', 'semantic_core', 'recall_fulltext'."
    )
    tool: MultiLaneTool
    lane: Lane
    params: FulltextParams | SemanticParams


class MultiLaneSearchRequest(BaseModel):
    """
    Request for multi-lane sequential execution of search tools.

    The executor MUST execute entries in the given order, one by one,
    respecting backend rate limits (no internal parallelism by default).
    """

    lanes: list[MultiLaneEntryRequest]
    trace_id: str | None = None


class MultiLaneEntryResponse(BaseModel):
    """
    One lane execution result with its logical name and underlying SearchToolResponse.
    """

    lane_name: str
    tool: MultiLaneTool
    lane: Lane
    response: SearchToolResponse


class MultiLaneSearchMeta(BaseModel):
    took_ms_total: int | None = None
    trace_id: str | None = None


class MultiLaneSearchResponse(BaseModel):
    """
    Response for multi-lane sequential execution.

    results: list of lane results in the same order as the request.
    meta: optional overall timing/trace information.
    """

    results: list[MultiLaneEntryResponse]
    meta: MultiLaneSearchMeta | None = None

from enum import Enum

class MultiLaneStatus(str, Enum):
    success = "success"
    error = "error"
    partial = "partial"  # 将来、部分成功を扱いたい場合用（今は使わなくてもOK）


class MultiLaneEntryError(BaseModel):
    """
    Error information for a single lane execution inside a multi-lane batch.
    """
    code: str = Field(
        description="Machine-readable error code, e.g. 'timeout', 'backend_403', 'validation_error'."
    )
    message: str = Field(
        description="Human-readable short description of the error."
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional backend-specific details (HTTP status, trace IDs, etc.).",
    )


class MultiLaneEntryResponse(BaseModel):
    """
    One lane execution result with its logical name and underlying SearchToolResponse.
    """

    lane_name: str
    tool: MultiLaneTool
    lane: Lane

    status: MultiLaneStatus = Field(
        description="Execution status of this lane: success / error / partial."
    )
    took_ms: int | None = Field(
        default=None,
        description="Elapsed time in milliseconds for this lane execution (if measured).",
    )

    # 成功時のみ埋まる
    response: SearchToolResponse | None = Field(
        default=None,
        description="Underlying search tool response if status == success.",
    )

    # 失敗時のみ埋まる
    error: MultiLaneEntryError | None = Field(
        default=None,
        description="Error information if status != success.",
    )


class MultiLaneSearchMeta(BaseModel):
    took_ms_total: int | None = None
    trace_id: str | None = None
    success_count: int | None = None
    error_count: int | None = None


class MultiLaneSearchResponse(BaseModel):
    """
    Response for multi-lane sequential execution.

    results: list of lane results in the same order as the request.
    meta: optional overall timing/trace information.
    """

    results: list[MultiLaneEntryResponse]
    meta: MultiLaneSearchMeta | None = None

```
## MCP側の処理例
```python
async def run_multilane_search(req: MultiLaneSearchRequest) -> MultiLaneSearchResponse:
    results: list[MultiLaneEntryResponse] = []
    t0 = time.perf_counter()
    success_count = 0
    error_count = 0

    for entry in req.lanes:
        lane_t0 = time.perf_counter()
        try:
            if entry.tool == "search_fulltext":
                resp = await search_fulltext(entry.params)
            elif entry.tool == "search_semantic":
                resp = await search_semantic(entry.params)
            else:
                raise ValueError(f"Unsupported tool in MultiLane: {entry.tool}")

            lane_t1 = time.perf_counter()
            results.append(
                MultiLaneEntryResponse(
                    lane_name=entry.lane_name,
                    tool=entry.tool,
                    lane=entry.lane,
                    status=MultiLaneStatus.success,
                    took_ms=int((lane_t1 - lane_t0) * 1000),
                    response=resp,
                    error=None,
                )
            )
            success_count += 1

        except Exception as e:
            lane_t1 = time.perf_counter()
            # ここは実際には exception の種類に応じて code をセット
            results.append(
                MultiLaneEntryResponse(
                    lane_name=entry.lane_name,
                    tool=entry.tool,
                    lane=entry.lane,
                    status=MultiLaneStatus.error,
                    took_ms=int((lane_t1 - lane_t0) * 1000),
                    response=None,
                    error=MultiLaneEntryError(
                        code=type(e).__name__,
                        message=str(e),
                        details={},
                    ),
                )
            )
            error_count += 1

    t1 = time.perf_counter()
    return MultiLaneSearchResponse(
        results=results,
        meta=MultiLaneSearchMeta(
            took_ms_total=int((t1 - t0) * 1000),
            trace_id=req.trace_id,
            success_count=success_count,
            error_count=error_count,
        ),
    )
```
## プロンプト例
グローバルにフラグenable_multi_runをおいて制御
```yaml
- Normally you call search_fulltext / search_semantic individually.
- However, after you finish wide search and code profiling,
  if enable_multi_run is true, you should call the tool `run_multilane_search` to execute multiple lanes in one shot.
- When you use run_multilane_search:
  - Prepare up to 3–4 lanes (e.g., semantic, recall_fulltext, precision_fulltext).
  - Each lane must have:
    - lane_name (human readable)
    - tool (search_fulltext or search_semantic)
    - lane (fulltext or semantic)
    - params (FulltextParams or SemanticParams).

## 実装メモ
- `run_multilane_search` は `enable_multi_run` フラグが true のときに wide_search/code_profiling 後で呼び出すようにプロンプトにも記載したため、実装側では sequential execution を保証するだけでなく Service 側の `MultiLaneSearchRequest` で trace_id や success/error counts を集約しています。
```
### ツール定義のプロンプト（案なので修正か）
```yaml
tools:
  run_multilane_search:
    description: >
      Execute multiple search lanes (fulltext and/or semantic) sequentially in one tool call.
      Use this after you have already decided all lane queries and parameters
      (typically after code_profiling). Do not explain each lane in detail while
      the tool is running; instead, briefly summarize the overall outcome afterwards.
```

## 追加プロンプト改良案
グローバルポリシーで熟考をさけるように

```yaml
global_policies:
  - Always respect lane definitions in this config.
  - Never use semantic_style: "original_dense" (it is disabled in v1.3).
  - Do not mix code systems within a single lane.
  - Prefer recall-first design, then tune toward precision using mutate_run.
  - At the beginning of a search task (or when the user changes the task),
    clearly show your overall multi-lane plan (which lanes, which tools, which parameters).
  - During tool execution, keep explanations short (1–2 sentences) and prioritize
    moving to the next tool call if the next step is already clear.
  - Always answer the human in Japanese, but keep identifiers and JSON keys in English.
```
言語ポリシーでも伝える
```yaml
language_policy:
  user_interaction:
    input_language: Japanese
    output_language: Japanese
    rules:
      # フェーズ1: プランニング
      - At the beginning of a search task, explain your overall multi-lane plan
        (lanes, tools, key parameters) in Japanese, in a few short paragraphs.
      # フェーズ2: ツール実行中
      - After each tool call, do NOT deeply analyze or summarize all fields.
        Give at most 1–2 short sentences in Japanese focusing on:
        (a) whether the tool succeeded, and
        (b) what you will do next.
      - If the next step is already defined by the pipeline, you may omit explanations
        and immediately issue the next tool call.
      # フェーズ3: 結果提示
      - Once the main fusion/snippets step is complete and you are ready to present
        candidates to the human, you may provide a more detailed explanation and comparison
        of the results in Japanese.
      # 共通ルール
      - Keep technical identifiers (lane names, tool names, JSON keys, code labels) in English.
      - When quoting snippets from patents, preserve original language (JA/EN) as-is.
```
