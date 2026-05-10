# FinOps MCP Agent

An MCP-native, multi-cloud cost intelligence platform. Ask cloud cost questions in plain English — get instant answers with interactive charts across AWS, Azure, and GCP.

> **Current state:** 4 MCP servers (BQ, SQL Server, Analytics, File) + single Gemini 2.5 Pro agent + FastAPI + React dashboard with SSE streaming.

**[▶ Watch Demo](https://drive.google.com/file/d/1UMCAsbRWVjwdFg1FdogLk5IyklzAP_Ox/view?usp=drive_link)** | **[Source Code](https://github.com/Dhwani-S/finops-mcp-agent)**

---

## Architecture

```
┌──────────────────────────┐
│  Browser (Dashboard)     │
│  Chat + Charts + Tables  │
└────────────┬─────────────┘
             │ HTTP POST /chat
             │ SSE /stream
┌────────────▼─────────────┐
│  Web API (FastAPI)        │  ← thin HTTP layer, NOT an MCP server
│  Streams agent events     │     streams thinking/tool-calls/answers to browser
│  to browser via SSE       │
└────────────┬─────────────┘
             │ in-process
┌────────────▼──────────────────────────────────────────────────────┐
│                        FINOPS AGENT (Gemini)                      │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐   │
│  │ System       │  │ Elicitation  │  │ Validation Layer       │   │
│  │ Prompt       │  │ Layer        │  │ (post-query checks)    │   │
│  └──────────────┘  └──────────────┘  └────────────────────────┘   │
│                                                                   │
│  ┌──────────┐                                                     │
│  │ MCP      │──stdio──┬──────────┬───────────┬──────────┐         │
│  │ Client   │         │          │           │          │         │
│  └──────────┘         │          │           │          │         │
└───────────────────────┼──────────┼───────────┼──────────┼─────────┘
                        │          │           │          │
                   ┌────▼────┐┌────▼────┐┌─────▼─────┐┌──▼──────┐
                   │ BQ      ││ SQL     ││ Analytics ││ File    │
                   │ Server  ││ Server  ││ Server    ││ Server  │
                   │         ││         ││           ││         │
                   │ DATA    ││ DATA    ││ COMPUTE   ││ STATE   │
                   └─────────┘└─────────┘└───────────┘└─────────┘
```

**Key insight:** MCP is for LLM ↔ tool communication. The dashboard is a human ↔ agent surface — different protocol, different concern. The Web API streams agent events to the browser. The frontend decides how to render data (chart, table, card). No `push_component` tool needed.

---

## Design Principles

1. **Generic tools, intelligent context.** Data tools are generic (`run_bq_query(sql)`, not `get_aws_costs()`). The LLM writes SQL guided by schema Resources. New use cases don't require new tools.
2. **Infrastructure boundaries = server boundaries.** BQ and SQL Server are separate MCP servers because they have different credentials, failure modes, SQL dialects, and timeouts.
3. **MCP primitives used for real reasons.** Tools for actions, Resources for context, Prompts for structured workflows — not just to check boxes.
4. **Elicitation before execution.** Financial data demands correctness. Ambiguities are tiered (safe defaults → warn after → ask before → block) to balance speed and accuracy.
5. **LLM IS the insights engine.** Synthesis, narration, recommendations ranking — the LLM handles natively. Tools handle what the LLM can't: database access, statistical computation, external APIs.
6. **MCP for tools, HTTP for humans.** MCP servers serve the agent. The dashboard talks to a Web API (FastAPI) that wraps the agent — separate concerns, separate protocols.
7. **Session-progressive.** Each EAGV3 session adds a layer (memory, multi-agent, A2A, A2UI, channels) without rewriting MCP servers.

---

## MCP Servers

### 1. `finops_bq_server.py` — BigQuery Data

Serves multi-cloud cost data and GCP recommendations from BigQuery. The LLM writes SQL guided by schema Resources.

| Primitive | Name | Purpose |
|-----------|------|---------|
| **Tool** | `run_bq_query(sql)` | Execute read-only BigQuery SQL (SELECT/WITH only, guarded, 500 GB cap, 500 row limit) |
| **Resource** | `schema://bq/azure/daily_costs` | Azure daily cost table schema |
| **Resource** | `schema://bq/aws/daily_costs` | AWS daily cost table schema |
| **Resource** | `schema://bq/gcp/daily_costs` | GCP daily cost table schema |
| **Resource** | `schema://bq/azure/utilization_metrics` | Azure utilization metrics schema |
| **Resource** | `schema://bq/azure/recommendation_savings` | Azure recommendation savings tracking |
| **Resource** | `schema://bq/gcp/recommendations` | GCP recommendations schema (business-mapped) |
| **Resource** | `schema://bq/gcp/pricing_export` | GCP pricing catalog — list + contract prices per SKU |
| **Resource** | `guide://query-patterns` | Common SQL patterns (aggregation, comparison, trends, date handling) |
| **Resource** | `guide://cloud-taxonomy` | Cross-cloud service mapping + table locations (BQ vs SQL Server) |
| **Prompt** | `cost_breakdown` | "Analyze {cloud} costs grouped by {dimension} for {period}" |
| **Prompt** | `period_comparison` | "Compare {metric} between {period_a} and {period_b}" |
| **Prompt** | `anomaly_investigation` | "Investigate the cost anomaly for {service} on {date}" |

**BQ Table inventory (from Cost_Source_Tables spreadsheet):**
- Azure costs: `cie-costmanagement-803717.azure.daily_usage_costs`
- AWS costs: `cie-costmanagement-803717.aws.aws_daily_usage_extended_costs`
- GCP costs: `cie-costmanagement-803717.gcp.daily_usage_costs`
- Azure utilization: `cie-costmanagement-803717.azure.azure_utilization_metrics`
- Azure savings: `cie-costmanagement-803717.azure.recommendation_savings`
- GCP recommendations: `cie-costmanagement-803717.reporting_data.gcp_recommendation`
- GCP pricing catalog: `cie-costmanagement-803717.published_gcp.gcp_cloud_pricing_export`

**Note:** AWS and Azure recommendations are in SQL Server (`reporting.aws_recommendations`, `reporting.azure_recommendations`), served by the SQL Server MCP server.

### 2. `finops_sql_server.py` — SQL Server Data

Serves data from on-prem/Azure SQL Server. Dynamic schema discovery since SQL Server tables change more frequently.

| Primitive | Name | Purpose |
|-----------|------|---------|
| **Tool** | `run_sql_query(sql)` | Execute read-only T-SQL (SELECT/WITH only, guarded) |
| **Tool** | `get_table_schema(schema_name, table_name)` | Discover table shapes dynamically |
| **Resource** | `schema://sql/available-tables` | List of schemas/tables the agent can query |
| **Resource** | `guide://tsql-patterns` | T-SQL specific patterns (date functions, JOIN syntax) |
| **Prompt** | `sql_exploration` | "Explore {table}: row count, sample data, column distributions" |

**Why `get_table_schema` is a Tool (not Resource):** SQL Server schemas change. Dynamic discovery > stale definitions. BQ schemas are Resources because they're documented and stable.

### 3. `finops_analytics_server.py` — Computation Engine

Handles everything the LLM can't reliably compute: statistics, forecasting, recommendation scoring, result validation. Pure computation — no database access. Pricing data comes from the cost tables via BQ/SQL servers.

| Primitive | Name | Purpose |
|-----------|------|---------|
| **Tool** | `detect_anomalies(data_json, method, sensitivity)` | Z-score/IQR anomaly detection on time-series data |
| **Tool** | `forecast(data_json, periods_ahead, method)` | Linear regression / exponential smoothing with confidence intervals |
| **Tool** | `calculate_growth(data_json, period)` | MoM, WoW, QoQ, YoY growth rates with proper calendar alignment |
| **Tool** | `score_recommendations(recommendations_json)` | Deterministic ranking by savings × confidence × effort |
| **Tool** | `validate_results(data_json, query_context)` | Post-query sanity checks (negative costs, insane growth, null rates) |
| **Resource** | `taxonomy://cloud-services` | Cross-cloud service mapping with normalized names |
| **Resource** | `reference://anomaly-thresholds` | Default threshold configs by spend tier (<$1K, $1K-$3K, >$3K) |
| **Resource** | `reference://pricing-data-guide` | Where actual pricing data lives in our cost tables (columns per cloud) |
| **Resource** | `elicitation://rules` | Tiered ambiguity rules for every query dimension |
| **Resource** | `elicitation://cost-columns` | What each cost column means per cloud and when to use which |
| **Resource** | `elicitation://data-quality` | Known data gaps, null rates by field, freshness SLAs |
| **Prompt** | `investigate_anomaly` | "Given these anomaly scores for {service}, explain likely cause" |
| **Prompt** | `forecast_summary` | "Summarize forecast: projected spend, confidence, risk level" |

### 4. `finops_file_server.py` — Reports & Persistence

Sandboxed file operations for saving reports, analyses, and CSV exports. **No in-place patch tools:** reports are **full rewrite** (`write_file` overwrites) or **append-only** (`append_file`). That avoids fragile match-and-replace against stale file content from the model.

| Primitive | Name | Purpose |
|-----------|------|---------|
| **Tool** | `write_file(path, content)` | Save or replace entire report/analysis under `reports/` sandbox |
| **Tool** | `append_file(path, content)` | Append to an existing file (e.g. log-style or incremental sections) |
| **Tool** | `read_file(path)` | Read a saved file |
| **Tool** | `list_files(subdir)` | List saved files |
| **Tool** | `delete_file(path)` | Remove a file |
| **Tool** | `export_csv(filename, json_data)` | Convert JSON query results to CSV |
| **Resource** | `report://{filename}` | Dynamic resource: read any saved report by URI |
| **Prompt** | `executive_summary` | "Generate a {period} executive cost summary for {audience}" |
| **Prompt** | `chargeback_report` | "Generate chargeback report for {team} covering {period}" |

### Web API Layer (Not an MCP Server)

The Web API is a thin FastAPI shell that wraps the agent and streams events to the browser. It handles:

- `POST /chat` — Accept user messages, run agent loop
- `GET /stream` — SSE endpoint streaming agent events (thinking, tool calls, results, final answer)
- `GET /reports` — List/download saved reports from the File Server sandbox

The **frontend** (HTML/JS dashboard + chat) decides how to render agent output — charts, tables, cards. The LLM returns structured data; rendering logic lives in the UI, not in MCP.

---

## Primitive Totals

| Server | Tools | Resources | Prompts | Domain |
|--------|-------|-----------|---------|--------|
| BQ Server | 1 | 9 | 3 | Data retrieval (BigQuery) |
| SQL Server | 2 | 2 | 1 | Data retrieval (SQL Server) |
| Analytics Server | 5 | 6 | 2 | Computation, validation |
| File Server | 5 | 1 (dynamic) | 2 | Reports & persistence |
| **Totals** | **13** | **18** | **8** | |

---

## Elicitation Protocol

Financial data demands correctness. The agent follows a tiered elicitation protocol:

### Tier 0: Safe Defaults (Don't Ask)
| Ambiguity | Default | Rationale |
|-----------|---------|-----------|
| Cloud provider not specified | All clouds | Showing more is safe; hiding data is dangerous |
| "Last month" | Previous calendar month | Universal business convention |
| "This quarter" | Current calendar quarter | Unambiguous |
| Group-by not specified | By service | Most useful default |

### Tier 1: Warn After (Show Result + Flag Assumptions)
| Ambiguity | Behavior |
|-----------|----------|
| Cost column ambiguity | Use `total_cost`, note which column and why |
| Incomplete period | Show data, flag: "April data is partial (through Apr 25)" |
| Null categories | Show data, flag: "12% of spend has no project_name tag" |
| Stale data | Show data, flag: "Data last updated: Apr 28, 11:30 PM UTC" |

### Tier 2: Ask Before (Must Confirm)
| Ambiguity | Why Critical |
|-----------|-------------|
| Scope (team/project) | Financial data leakage — developers shouldn't see org-wide |
| Chargeback allocation method | "Equal split" vs "by usage" changes numbers by 30%+ |
| Recommendation actions | Deleting resources / purchasing RIs = real money |
| Budget source confirmation | Which budget table? Manual override? |
| Cross-cloud comparison basis | $/vCPU vs $/instance vs total spend |

### Tier 3: Block (Refuse Without Confirmation)
| Situation | Response |
|-----------|----------|
| Org-wide financial data with no scope | Require scope confirmation |
| Anomaly detection on <7 days baseline | "Need at least 14 days of baseline" |
| Forecast confidence >50% variance | "Not enough data for reliable projection" |

### Post-Query Validation
Every query result passes through `validate_results()` before being shown:
- No negative total costs
- Growth rates within sane bounds (<500%)
- Sum of parts ≈ total (flag discrepancies)
- Zero-row results flagged as potential access issues
- Null rates >20% flagged for group-by columns

---

## Feature Coverage

| Feature | Implementation | What Does the Work |
|---------|---------------|-------------------|
| Cost queries | BQ/SQL Server tools | LLM writes SQL, guided by schema Resources |
| Recommendations | BQ tool + `score_recommendations` | Data in BQ tables, analytics scores them |
| Insights engine | LLM itself | Synthesis across multiple query results |
| Anomaly detection | `detect_anomalies` tool | Z-score/IQR — LLM can't do statistics reliably |
| Forecasting | `forecast` tool | Regression + confidence intervals |
| Price calculator | `estimate_cost` tool | External pricing APIs + computation |
| Price comparator | `compare_pricing` tool | Cross-cloud normalization |
| Report generation | LLM + File Server tools | LLM writes report, tool saves it |
| Visualization | Web API + Frontend | Agent returns data, frontend renders charts/tables |

---

## Example Flow

```
User: "Show me top 5 expensive services, save a report, display on dashboard"

1. Agent reads Resource: schema://bq/azure/daily_aggregated_costs  (Azure schema)
   Agent reads Resource: schema://bq/aws/daily_usage_extended_costs (AWS schema)
   Agent reads Resource: schema://bq/gcp/daily_aggregated_costs    (GCP schema)

2. Agent reads Resource: elicitation://rules
   → Tier 0: no cloud specified → default to all clouds ✓
   → Tier 0: no period specified → default to last 30 days ✓
   → Tier 1: will flag cost column used in response ✓

3. Agent calls BQ: run_bq_query("SELECT service, SUM(total_cost)...")
   → Returns: [{service: "EC2", cost: 245000}, {service: "Azure VMs", cost: 178000}, ...]

4. Agent calls Analytics: validate_results(data, context)
   → Passes: no negatives, sane totals, complete date range ✓

5. Agent calls File: write_file("top_services_2026-04.md", report_content)
   → Saved to reports/top_services_2026-04.md

6. Agent responds (streamed via Web API → SSE → browser):
   "Here are the top 5 most expensive services across all clouds (last 30 days,
    using total_cost which includes support + tax):
    [structured data: {type: 'bar_chart', labels: [...], values: [...]}]
    [structured data: {type: 'table', headers: [...], rows: [...]}]
    Report saved to: top_services_2026-04.md
    ⚠️ Data as of: Apr 28, 2026 11:30 PM UTC"

7. Frontend receives streamed events, renders charts/tables from structured data.
```

---

## Session-by-Session Growth Plan

| Session | What Gets Added | Where It Goes |
|---------|----------------|---------------|
| **4 — MCP** | 4 MCP servers + single agent + Web API + dashboard | ← **current** |
| **5 — Planning** | Chain-of-Thought, ReACT loop in agent | `agent/finops_agent.py` |
| **6 — Cognitive** | 4-layer pipeline (Perceive→Memory→Decide→Act) | `agent/cognitive.py` |
| **7 — Memory/RAG** | 3-tier memory (preferences, past queries, cost facts) | New MCP server: `finops_memory_server.py` |
| **8 — Multi-Agent** | Specialist sub-agents (cost analyst, anomaly detector) | `agent/agents/` with DAG coordinator |
| **9 — Browser** | Playwright: screenshot cloud console, scrape pricing | New tools on Analytics server |
| **11 — Channels** | Slack/GChat adapters | `channels/` adapter pattern |
| **13 — A2A** | Agent-to-agent protocol between specialists | Protocol layer on agents |
| **14 — A2UI** | Dynamic UI generation at runtime | Upgrade Web API + frontend |
| **15 — Routing** | Multi-model routing + cost tracking | Agent-level model selection |

---

## Project Structure

```
finops-mcp-agent/
├── mcp_servers/
│   ├── finops_bq_server.py          # BigQuery data access + schema Resources
│   ├── finops_sql_server.py         # SQL Server data access
│   ├── finops_analytics_server.py   # Computation, pricing, validation
│   └── finops_file_server.py        # Report CRUD (sandboxed to reports/)
├── agent/
│   ├── finops_agent.py              # Gemini agent loop (connects all 4 servers)
│   └── models.py                    # Data classes
├── api/
│   └── server.py                    # FastAPI web layer (HTTP + SSE)
├── frontend/
│   ├── index.html                   # Dashboard + chat UI
│   ├── app.js                       # SSE client, rendering logic
│   └── styles.css
├── resources/
│   ├── schemas/                     # Table schemas (loaded as MCP Resources)
│   │   ├── bq_azure_daily_costs.json
│   │   ├── bq_aws_daily_costs.json
│   │   ├── bq_gcp_daily_costs.json
│   │   └── bq_recommendations.json
│   ├── guides/                      # Query patterns, taxonomy
│   │   ├── query_patterns.md
│   │   └── cloud_taxonomy.json
│   └── elicitation/                 # Financial data safety rules
│       ├── rules.json
│       ├── cost_columns.json
│       └── data_quality.json
├── reports/                         # Sandbox for file CRUD operations
├── config/
│   └── settings.py                  # Credentials, project IDs, endpoints
├── requirements.txt
├── .env.example
└── README.md
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| MCP Framework | `mcp[cli]` (FastMCP) |
| LLM | Gemini 2.5 Pro / Flash (via `google-genai`) |
| BigQuery | `google-cloud-bigquery` |
| SQL Server | `pymssql` |
| Analytics | `numpy`, `scipy` (stats), `requests` (pricing APIs) |
| Web API | FastAPI + `sse-starlette` |
| Frontend | Vanilla HTML/JS (dashboard + chat) |
| Config | `python-dotenv` |

---

## Quick Start

```bash
# 1. Clone and setup
cd finops-mcp-agent
python -m venv .venv
.venv\Scripts\Activate.ps1    # Windows
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your GEMINI_API_KEY, GCP credentials, SQL Server creds

# 3. Run the agent
python agent/finops_agent.py

# 4. Test individual MCP servers (dev inspector)
mcp dev mcp_servers/finops_bq_server.py
mcp dev mcp_servers/finops_analytics_server.py
```

---

## Relationship to Existing Projects

| Project | Role | Status |
|---------|------|--------|
| `Finops_Project/finops-agent` | Original vibecoded agent (Google ADK, supervisor pattern) | Reference only |
| `Finops_Project/finops-mcp-agent` | **This project** — MCP-native rebuild | Active development |
| `Session_1_web_extn` (Vantage) | Chrome extension (Session 1-3 assignment) | Separate project, not integrated |
| `AI_Workshop/MCP` | Practice MCP scripts from course | Pattern reference |

---

## Implementation Notes & Known Risks

Items flagged during architecture review that must be addressed during implementation.

### 1. SQL Guardrails (Critical — Financial Data)

The `run_bq_query` and `run_sql_query` tools must enforce more than a `^(SELECT|WITH)` regex. Prefer a **parser or dialect-aware allowlist** for “read-only single statement”; regex is at most a fast pre-filter.

- **Single-statement parser:** Reject queries containing `;` after stripping comments/strings. Prevents `SELECT ...; DROP TABLE ...`.
- **Bytes-billed cap:** Set `maximum_bytes_billed` on BigQuery jobs (e.g., 1 GB) to prevent runaway scans.
- **Query timeout:** Hard timeout per query (30s BQ, 15s SQL Server). Existing BQ server has this; SQL Server needs it.
- **Row / response limits:** Truncate or refuse unbounded result sets; return clear errors when limits are hit.
- **Table allowlist (optional):** If deployed beyond the developer, restrict to known cost/recommendation tables only.
- **No DDL/DML keywords:** Explicitly reject `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `MERGE`, `GRANT`, `REVOKE` anywhere in the query string regardless of position.

### 2. File server — overwrite + append only (no patch tool)

The File Server tool table uses **`write_file` (full replace)** and **`append_file` (additive)** only. **No `edit_file`:** match-and-replace is a footgun for agents (wrong match corrupts reports silently). See also **§5 Atomic File Writes** below.

### 3. Structured Output Contract (Agent → Frontend)

The agent returns structured data (chart specs, table data) in its responses. The frontend renders them. The contract between agent and frontend must be:

- **Well-defined** — a clear JSON shape for each component type (bar chart, table, metric card, alert).
- **Documented** — so the system prompt can instruct the LLM on valid output shapes.
- **Validated in the frontend** — graceful fallback if the LLM produces malformed structures.

### 4. Stdio Transport — Local Only

Four stdio MCP servers (4 Python processes) per agent session is fine for local dev and the course project. For production/multi-user deployment:

- Swap to SSE or streamable HTTP transport (e.g. `mcp.run(transport="sse")` in FastMCP). **Tool handlers stay the same;** you still design **session identity, auth, and pooling** for shared long-lived servers (not a literal one-line production cutover).
- Consider collapsing stable, low-traffic servers (e.g., File into another process) once access patterns are clear.

### 5. Atomic File Writes

`write_file` should write to a temp file first, then rename — not write directly. Prevents partial writes on crash/timeout from corrupting reports. Standard pattern:

```python
tmp = path + ".tmp"
write(tmp, content)
os.replace(tmp, path)  # atomic on same filesystem
```

---

## Testing & Optimization Findings (May 10, 2026)

### Baseline Metrics (20 queries, no tool routing)

| Metric | Value |
|--------|-------|
| Total tokens | 1.7M |
| LLM rounds | 450 |
| Tool calls | 240 |
| Cached tokens | 1.5M (88%) |
| Tokens/query | ~85K |

### Tool Routing Experiment

Added keyword-based tool routing (`_route_query()`) that maps query keywords to relevant MCP servers, reducing the tool set per query (e.g., GCP query → only BQ+Analytics = 14 tools instead of 24).

**Result (21 queries):** Total tokens dropped to 1.6M (-6%), tokens/query to ~76K (-10%). But cache hit rate dropped from 88% → 73% because changing the tool set breaks Gemini's implicit cache prefix matching. Net effect: **~25% more expensive** in effective tokens.

**Decision:** Reverted tool routing. The cache penalty outweighs the tool-count savings. Keeping all 24 tools always preserves the cacheable prefix. Code remains in `agent.py` (behind `_route_query`) but is not called.

### Determinism Analysis

**Highly deterministic (consistent across runs):**
- Scope enforcement (SCOPE REQUIRED guardrail triggers every time)
- Dry-run before execution for BQ queries
- Identity lookup flow (core_id → user → projects)
- Final dollar amounts (identical across runs)
- Correct server selection (BQ for GCP, SQL for Azure, File for reports)

**Acceptably non-deterministic:**
- SQL column aliases (`total_cost` vs `spend`) — both work
- Query strategy (UNION ALL vs `run_multi_cloud_cost_query`) — different approach, same result
- Post-processing tool choice (`format_currency` vs `convert_to_chart_data`)

**Problematically non-deterministic (fixed):**
- JSON serialization bugs: LLM re-serializes BQ result JSON as string arg to analytics tools, occasionally introduces typos (e.g., stray `.` in JSON). **Fix:** Added JSON repair in `_parse_data()`.
- No retry on tool failure: agent says "I'll correct it" but doesn't retry. **Fix:** Added 1-retry logic in agent loop.
- Inconsistent report formatting (download links vs plain bullets) — presentation-level, not data-level.

### Known Issues

1. **`detect_anomalies` JSON pass-through:** The model copies ~1700 chars of BQ JSON into `data_json` string argument. This is fragile — any LLM typo in the copy breaks parsing. Mitigated with JSON repair, but the root cause is the tool API design (should accept structured data, not a JSON string).
2. **Azure recommendations data:** Only 1 cost recommendation exists in the latest snapshot with no savings estimate. Other categories (Security, Performance, HighAvailability) return 0 rows for the latest date. This is a data issue, not an agent issue.
3. **Proactive follow-up inconsistency:** Sometimes the agent proactively suggests next steps (e.g., "check reservations"), sometimes it just asks generic "anything else?" — depends on LLM mood.

### Post-Fix Run (15 queries, after JSON repair + routing revert)

| Metric | Baseline | With routing | After fix | Per-query (fix vs base) |
|--------|----------|-------------|-----------|------------------------|
| Total tokens | 1.7M (20q) | 1.6M (21q) | **1.3M (15q)** | 87K vs 85K (≈same) |
| LLM rounds | 450 | 492 | **276** | 18.4 vs 22.5 (-18%) |
| Tool calls | 240 | 261 | **160** | 10.7 vs 12.0 (-11%) |
| Cache rate | 88% | 73% | **83%** | recovered |

**Improvements confirmed:**
- `detect_anomalies` succeeded — model generated clean JSON, correct anomaly result ($874K spike on Apr 29)
- Self-healing on wrong param: model called `format_currency(json_data=...)` (wrong param name) → got Pydantic error → immediately retried with correct `data_json` param. Clear error messages enable natural retry.
- Cache rate recovered to 83% after routing revert (vs 73% with routing)
- Agent added smart partial-month disclaimer: "This Month reflects a partial month's spend to date, so the decrease shown is expected"
- Proactive follow-up still inconsistent (didn't suggest reservations for Azure recs — non-deterministic LLM behavior)
