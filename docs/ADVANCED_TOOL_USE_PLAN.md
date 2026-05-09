# Advanced Tool Use — Implementation Plan

**Date:** 2026-05-09
**Branch:** `feat/advanced-tool-use-plan`
**Reference:** [Anthropic — Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
**Status:** Planning

---

## Context

Our agent currently has 13 tools across 4 MCP servers. As queries grow in complexity (multi-cloud comparisons, multi-step anomaly → forecast chains), two problems emerge:

1. **Context pollution:** Large BQ/SQL results (500 rows of JSON) enter Gemini's context, forcing us to truncate at 4,000 chars (`_MAX_TOOL_RESULT_CHARS`). This loses data and can cause hallucination.
2. **SQL invocation errors:** The system prompt is ~200+ lines largely because Gemini needs detailed instructions on which tables, columns, date filters, and SQL patterns to use. Schema Resources help, but tool-level examples would reduce errors further.

---

## Pattern 1: Tool Use Examples (Priority: HIGH, Effort: LOW)

### Problem
Gemini frequently makes errors in SQL generation:
- Wrong cost column (`azure_cost` vs `total_cost`)
- Missing date freshness filters on recommendation tables
- Wrong table for a given cloud
- Incorrect date functions (BigQuery SQL vs T-SQL)

The system prompt compensates for this with extensive routing tables and rules, but it's brittle — every new table or edge case requires more prompt engineering.

### Solution
Add 2-3 concrete SQL examples to each data-access tool's description. The model learns correct invocation patterns from examples, not just schema definitions.

### Implementation Steps

#### Step 1: Add examples to `run_bq_query` tool description

Add to `finops_bq_server.py` tool docstring:

```
Examples:

1. Azure spend by service (last month):
   SELECT service_name, SUM(total_cost) as total
   FROM `cie-costmanagement-803717.azure.daily_aggregated_costs`
   WHERE datetime >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH)
     AND datetime < DATE_TRUNC(CURRENT_DATE(), MONTH)
   GROUP BY service_name ORDER BY total DESC LIMIT 20

2. AWS top services (this quarter):
   SELECT line_item_product_code, SUM(total_cost) as total
   FROM `cie-costmanagement-803717.aws.aws_daily_usage_extended_costs`
   WHERE line_item_usage_start_date >= DATE_TRUNC(CURRENT_DATE(), QUARTER)
   GROUP BY line_item_product_code ORDER BY total DESC LIMIT 10

3. GCP recommendations (latest snapshot only):
   SELECT recommendation_name, action_type, yearly_cost_savings, state
   FROM `cie-costmanagement-803717.reporting_data.gcp_recommendation`
   WHERE to_date = (SELECT MAX(to_date) FROM `cie-costmanagement-803717.reporting_data.gcp_recommendation`)
     AND state = 'ACTIVE'
   ORDER BY yearly_cost_savings DESC LIMIT 50
```

#### Step 2: Add examples to `run_sql_query` tool description

Add to `finops_sql_server.py` tool docstring:

```
Examples:

1. AWS recommendations (latest snapshot):
   SELECT TOP 20 * FROM reporting.aws_recommendations
   WHERE run_date = (SELECT MAX(run_date) FROM reporting.aws_recommendations)
   ORDER BY yearly_savings DESC

2. Azure K8s costs by namespace:
   SELECT TOP 20 namespace, SUM(cost) as total_cost
   FROM dbo.k8_cost_tracking_integrated
   GROUP BY namespace ORDER BY total_cost DESC

3. Schema discovery (always do first for unfamiliar tables):
   -- Call get_table_schema('reporting', 'aws_recommendations') before querying
```

#### Step 3: Add examples to analytics tools

Add to `detect_anomalies` and `forecast` tool docstrings showing expected input JSON format:

```
Example input for detect_anomalies:
{
  "data": [{"date": "2026-04-01", "cost": 45000}, {"date": "2026-04-02", "cost": 47000}, ...],
  "method": "zscore",
  "sensitivity": "medium"
}

Example input for forecast:
{
  "data": [{"date": "2026-01-01", "cost": 120000}, {"date": "2026-02-01", "cost": 125000}, ...],
  "periods_ahead": 3,
  "method": "linear"
}
```

### Validation
- Run the standard demo queries before and after
- Compare: SQL correctness, column selection, date filter usage
- Measure: system prompt token count reduction (goal: remove redundant routing rules)

### Expected Impact
- Fewer wrong-table and wrong-column errors
- Can slim down system prompt routing table
- Faster convergence on correct SQL (fewer retry rounds)

---

## Pattern 2: Programmatic Tool Calling (Priority: HIGH, Effort: MEDIUM)

### Problem
Multi-step queries dump all intermediate results into Gemini's context:

```
Step 1: run_bq_query(aws_costs)     → 200 rows JSON enters context
Step 2: run_bq_query(azure_costs)   → 200 rows JSON enters context
Step 3: run_bq_query(gcp_costs)     → 200 rows JSON enters context
Step 4: Gemini synthesizes          → 600 rows in context, mostly noise
```

This is why we have `_MAX_TOOL_RESULT_CHARS = 4000` — a truncation hack that loses data.

### Solution
Enable Gemini's native code execution so the model can write Python that orchestrates multiple tool calls, processes intermediate data, and returns only the final summary.

### Implementation Options

#### Option A: Gemini Native Code Execution (Preferred)

Gemini 2.5 Pro supports `tools=[{"code_execution": {}}]` natively. Enable it in `agent.py`:

```python
# In agent.py, when creating the chat config
tools_config = types.GenerateContentConfig(
    tools=[
        *self._tools,
        types.Tool(code_execution=types.CodeExecution())
    ]
)
```

**Pros:** No new MCP server, native support, sandboxed
**Cons:** Can only process data already in context (can't call MCP tools from code execution)

#### Option B: Python Executor MCP Tool (More Powerful)

Add a `run_python` tool to the Analytics MCP server that accepts a Python script + data:

```python
@mcp.tool()
async def run_python(code: str, data: str) -> str:
    """Execute Python code on provided data. Returns stdout.
    Use for: aggregating multi-query results, filtering large datasets,
    computing derived metrics, formatting final output.
    
    The code receives `data` as a JSON string variable.
    Only pandas, json, statistics modules available.
    """
    # Sandboxed execution with restricted builtins
    ...
```

**Pros:** Can process tool results before they enter context, full control
**Cons:** Security surface (needs sandboxing), new tool to maintain

#### Option C: Hybrid — Aggregation Wrapper Tools

Add thin wrapper tools that aggregate at the source:

```python
@mcp.tool()
async def run_bq_multi_cloud_query(
    aws_sql: str, azure_sql: str, gcp_sql: str,
    aggregation: str = "top_10_by_cost"
) -> str:
    """Run cost queries across all 3 clouds and return unified, aggregated result.
    Only the final aggregated data is returned — intermediate results are not exposed.
    """
```

**Pros:** Simplest, no code execution risk, domain-specific
**Cons:** Less flexible, more tools to maintain

### Recommended Approach
Start with **Option C** (safest, fastest) for the common multi-cloud pattern, then evaluate **Option B** for complex ad-hoc queries.

### Implementation Steps

#### Step 1: Add `run_multi_cloud_cost_query` to BQ server

```python
@mcp.tool()
async def run_multi_cloud_cost_query(
    aws_sql: str | None = None,
    azure_sql: str | None = None,
    gcp_sql: str | None = None,
    top_n: int = 10,
    sort_by: str = "cost"
) -> str:
    """Execute cost queries across multiple clouds and return a single unified result.
    Each SQL is optional — omit a cloud to skip it.
    Results are combined, sorted, and limited to top_n rows.
    Only the aggregated result enters the conversation — intermediate per-cloud
    results do not consume context.
    """
```

#### Step 2: Add `aggregate_and_summarize` to Analytics server

```python
@mcp.tool()
async def aggregate_and_summarize(
    data_json: str,
    group_by: str,
    metric: str = "cost",
    top_n: int = 10,
    include_percentages: bool = True
) -> str:
    """Aggregate raw query results: group, sum, sort, compute percentages.
    Use this to reduce large result sets before they enter context.
    Returns only the aggregated summary.
    """
```

#### Step 3: Update system prompt routing table

Add routing rule:
```
| Multi-cloud comparison | run_multi_cloud_cost_query (single call) |
| Reduce large results   | aggregate_and_summarize                  |
```

#### Step 4: Remove `_MAX_TOOL_RESULT_CHARS` truncation

Once aggregation tools are in place, the 4000-char truncation hack becomes unnecessary. Remove or increase the limit significantly.

### Validation
- Test: "Show me top 10 services across all clouds" — should be 1 tool call, not 3
- Test: "Compare AWS vs Azure spend by service" — unified result, no context overflow
- Measure: token usage per query (before vs after)
- Measure: answer quality on multi-cloud queries

### Expected Impact
- ~37% token reduction on complex queries (Anthropic's benchmark)
- Eliminate `_MAX_TOOL_RESULT_CHARS` truncation hack
- More accurate multi-cloud comparisons (all data processed before synthesis)
- Fewer hallucinations from context overflow

---

## Pattern 3: Tool Search / Deferred Loading (Priority: LOW)

### Current State
13 tools, 18 resources, 8 prompts across 4 servers. Total tool definition overhead is manageable (~15-20K tokens estimated).

### When to Revisit
- Agent grows to 30+ tools (e.g., after multi-agent phase)
- New MCP servers added (memory server, Slack adapter, K8s metrics)
- Tool definitions exceed 50K tokens

### Implementation (Future)
For Gemini, implement a custom tool search:
1. Store all tool definitions in a vector index
2. Add a `search_tools(query)` meta-tool
3. Agent discovers tools on-demand based on user query
4. Only matched tool definitions are loaded into context

**Not needed today. Parked for Phase 5+.**

---

## Execution Timeline

| Week | Task | Deliverable |
|------|------|-------------|
| 1 | Tool Use Examples | Examples added to all data-access tool docstrings |
| 1 | Validation | Run demo queries, compare SQL accuracy before/after |
| 2 | `run_multi_cloud_cost_query` | New BQ server tool for unified multi-cloud queries |
| 2 | `aggregate_and_summarize` | New Analytics server tool for result reduction |
| 2 | System prompt update | Add routing rules, trim redundant instructions |
| 3 | Remove truncation hack | Delete `_MAX_TOOL_RESULT_CHARS`, validate with large queries |
| 3 | Token measurement | Before/after token comparison on 10 standard queries |

---

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| SQL accuracy (correct table + column + filter) | ~80% | >95% |
| Token usage per multi-cloud query | ~15K | <10K |
| System prompt length | ~200 lines | <150 lines |
| `_MAX_TOOL_RESULT_CHARS` truncation | Active (4000 chars) | Removed |
| Multi-cloud query tool calls | 3+ per query | 1 per query |

---

## Files Modified

| File | Change |
|------|--------|
| `mcp_servers/finops_bq_server.py` | Add examples to `run_bq_query` docstring, add `run_multi_cloud_cost_query` tool |
| `mcp_servers/finops_sql_server.py` | Add examples to `run_sql_query` and `get_table_schema` docstrings |
| `mcp_servers/finops_analytics_server.py` | Add examples to analytics tools, add `aggregate_and_summarize` tool |
| `prompts/system_prompt.md` | Add routing rules for new tools, trim redundant instructions |
| `agent.py` | Remove or increase `_MAX_TOOL_RESULT_CHARS` |

---

## References

- [Anthropic — Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Anthropic — Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- [Gemini Code Execution](https://ai.google.dev/gemini-api/docs/code-execution)
