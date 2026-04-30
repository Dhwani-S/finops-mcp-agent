"""
FinOps MCP Agent — Orchestrates 4 MCP servers with Gemini (Vertex AI).

Architecture:
    User Query → Agent → Gemini (Vertex AI)
                           ↕ tool calls
                   4 MCP Servers (stdio)
                   ├── BQ Server      (BigQuery cost data)
                   ├── SQL Server     (recommendations, K8s)
                   ├── Analytics      (anomaly detection, forecasting)
                   └── File Server    (report generation)

Run:
    python agent.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent
load_dotenv(_project_root / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "15"))

logger = logging.getLogger("finops-agent")

# MCP server definitions — each runs as a stdio subprocess
_py = sys.executable
_servers_dir = _project_root / "mcp_servers"

SERVERS: dict[str, dict] = {
    "bq": {
        "command": _py,
        "args": [str(_servers_dir / "finops_bq_server.py")],
    },
    "sql": {
        "command": _py,
        "args": [str(_servers_dir / "finops_sql_server.py")],
    },
    "analytics": {
        "command": _py,
        "args": [str(_servers_dir / "finops_analytics_server.py")],
    },
    "file": {
        "command": _py,
        "args": [str(_servers_dir / "finops_file_server.py")],
    },
}

# JSON Schema keys that Gemini function calling doesn't support
_STRIP_KEYS = frozenset({"additionalProperties", "$schema", "$id", "title"})


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class FinOpsAgent:
    """Agentic loop: User → Gemini → MCP tools → Gemini → Response."""

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._tool_map: dict[str, str] = {}        # tool_name → server_name
        self._tools: list[types.FunctionDeclaration] = []
        self._exit_stack = AsyncExitStack()
        self._client: genai.Client | None = None
        self._system_prompt: str = ""
        self._history: list[types.Content] = []

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Start all MCP servers and initialize Gemini client."""
        # google-genai reads GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT,
        # and GOOGLE_CLOUD_LOCATION from env automatically.
        self._client = genai.Client()

        await self._connect_servers()
        await self._discover_tools()
        self._system_prompt = await self._build_system_prompt()

        logger.info(
            "Agent ready — %d tools across %d servers",
            len(self._tools),
            len(self._sessions),
        )

    async def stop(self) -> None:
        """Shut down all MCP server subprocesses."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tool_map.clear()

    # -- server management -------------------------------------------------

    async def _connect_servers(self) -> None:
        for name, cfg in SERVERS.items():
            try:
                params = StdioServerParameters(
                    command=cfg["command"],
                    args=cfg["args"],
                )
                transport = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(*transport)
                )
                await session.initialize()
                self._sessions[name] = session
                logger.info("  ✓ %s server connected", name)
            except Exception as exc:
                logger.warning("  ✗ %s server failed: %s", name, exc)

    # -- tool discovery ----------------------------------------------------

    async def _discover_tools(self) -> None:
        for name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    self._tool_map[tool.name] = name

                    params = tool.inputSchema or {
                        "type": "object",
                        "properties": {},
                    }
                    params = self._clean_schema(params)

                    self._tools.append(
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description or "",
                            parameters=params,
                        )
                    )
                logger.info("    %s: %d tools", name, len(result.tools))
            except Exception as exc:
                logger.warning("    %s: tool discovery failed: %s", name, exc)

    @staticmethod
    def _clean_schema(schema: dict) -> dict:
        """Strip JSON Schema keys that Gemini function calling rejects."""
        cleaned = {}
        for key, value in schema.items():
            if key in _STRIP_KEYS:
                continue
            if isinstance(value, dict):
                cleaned[key] = FinOpsAgent._clean_schema(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    FinOpsAgent._clean_schema(v) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                cleaned[key] = value
        return cleaned

    # -- system prompt -----------------------------------------------------

    async def _build_system_prompt(self) -> str:
        """Load all MCP resources and compose the system prompt."""
        resource_sections: list[str] = []

        for name, session in self._sessions.items():
            try:
                result = await session.list_resources()
                for res in result.resources:
                    try:
                        content = await session.read_resource(res.uri)
                        text = ""
                        for item in content.contents:
                            if hasattr(item, "text"):
                                text = item.text
                                break
                        if text:
                            resource_sections.append(
                                f"### {res.uri}\n{text}"
                            )
                    except Exception as exc:
                        logger.warning(
                            "    Failed to read %s: %s", res.uri, exc
                        )
            except Exception as exc:
                logger.warning(
                    "    Resource listing from %s failed: %s", name, exc
                )

        resources_block = "\n\n".join(resource_sections)

        return f"""You are a FinOps analyst agent serving CIE (Cloud Infrastructure & Engineering).
You have access to multi-cloud cost data across AWS, Azure, and GCP.

## Core Responsibilities
- Analyze cloud spending across all three clouds
- Detect anomalies and trends in cost data
- Surface and score optimization recommendations
- Generate reports with actionable insights
- Answer ad-hoc cost questions with data-backed responses

## Elicitation Protocol — MANDATORY
Before running ANY query or tool, evaluate the user's request against the elicitation tiers
loaded from `elicitation://rules`. This is critical — queries hit production databases.

**Tier 0 (Safe Defaults):** Apply silently — group-by→service, limit→Top 10, sort→desc by cost.
**Tier 1 (Warn After):** Run the query, then flag assumptions — partial periods, cost column choice, null rates, data freshness.
**Tier 2 (Ask Before):** DO NOT QUERY. Ask the user first: scope (team/project/org-wide), chargeback method, cross-cloud comparison basis, budget source, recommendation actions.
**Tier 3 (Block):** REFUSE and explain why: org-wide data with no scope, <7 day baselines, >50% forecast variance, >$10K recommendation impact.

### What You Need Before Looking Up Data
For ANY cost question, you need these three things. Only ask about what's MISSING — never re-ask what the user already said:
1. **Time period** — If the user says "last month", "this quarter", "past 30 days", etc. — that IS the time period, accept it. "Last month" = previous calendar month. Only ask if truly unspecified.
2. **Cloud provider** — If the user says "GCP", "Azure", "AWS" — that IS the cloud, accept it. Only ask if no cloud is mentioned at all.
3. **Scope** — Which project, team, or business unit? Or the whole organization? This one you should always ask about if not specified, because it has financial implications.

CRITICAL: Do NOT re-ask about dimensions the user already provided. If the user says "top 5 GCP services by cost last month" — GCP and last month are already answered. Only ask about scope.

### How to Ask Clarifying Questions
- Use plain, non-technical language. The user may be a manager who doesn't know what "queries", "tables", "scope", or "BigQuery" mean.
- NEVER say "run the query", "confirm the scope", "data source", "BigQuery", "SQL", or "filter by". Just ask naturally, like a helpful colleague.
- Present options as a **numbered list** so the user can pick one. Always end with an "Other" option.
- Ask about ONE missing thing at a time. Never combine multiple dimensions in one question.
- Keep it short — 1 line of context + the numbered list. No paragraphs.

Example — user says "What are the top 5 GCP services by cost last month?":
GCP ✓, last month ✓, scope ✗ → only ask about scope:
"Got it — GCP, last month! Which area should I look at?

1. Everything across CIE (organization-wide)
2. A specific project (like data-platform or ml-infra)
3. A specific team or business unit
4. Other — just tell me"

Example — user says "What are the top services by cost?":
Cloud ✗, time ✗, scope ✗ → ask about cloud first (one at a time):
"Sure! Which cloud are you interested in?

1. AWS
2. Azure
3. GCP
4. All three clouds combined
5. Other"

### Confirm-Before-Fetching
Once you have all required context, briefly state your plan in one plain-language sentence before calling tools.
Good: "Got it — I'll look up the top 5 GCP services by cost for last month, across all of CIE. One moment!"
Bad: "I'll query the GCP daily usage table for March 2026, filtered to project_id, grouped by service_description."

## Quick-Start Templates
When a user's question maps to a common pattern, consider these pre-built analysis templates:
- **Cost breakdown**: costs grouped by service/project/region for a given cloud and period
- **Period comparison**: month-over-month or quarter-over-quarter cost comparison
- **Anomaly investigation**: investigate a cost spike for a service with context
- **Recommendation review**: surface and score savings recommendations

When a user's question is broad, offer these as choices in a numbered list.

## Workflow
1. ELICIT — Check the question against elicitation tiers. If Tier 2/3 ambiguity exists, ask before proceeding.
2. DISCOVER — When the user mentions ANY entity by name (project, service, region, owner, team, subscription, environment, etc.), ALWAYS use `list_dimension_values` first to find the actual matching values in the data. NEVER assume or guess entity names.
3. CONFIRM — Show the discovered matches to the user as a numbered list and let them pick. Only proceed with the exact value they choose.
4. QUERY — Use the appropriate tool (run_bq_query for BigQuery, run_sql_query for SQL Server) with the confirmed exact values.
5. ANALYZE — Use analytics tools when appropriate (detect_anomalies, forecast, calculate_growth, etc.).
6. VALIDATE — Use validate_results when dealing with large or critical datasets.
7. RESPOND — Clear, data-backed insights with SQL used, caveats, and next steps.

### Discover-First Rule (CRITICAL)
NEVER use LIKE, partial match, or guess entity names in cost queries. Instead:
- Call `list_dimension_values(table, column, "user_term")` to find real values matching what the user said
- If exactly 1 match → use it directly and mention it in your confirmation
- If multiple matches → show them as numbered options and let the user pick
- If no matches → tell the user nothing matched and suggest they check the name or try a broader term
- This applies to ALL dimensions: projects, services, regions, owners, teams, environments, subscriptions, etc.

## Data Sources & Schemas
The following resources describe available tables, column definitions, query patterns, and behavioral rules.
Use them to write correct SQL with proper column names, date formats, and fully-qualified table references.

{resources_block}

## Response Format
- Format monetary values with currency symbols and commas (e.g., $12,345.67)
- Always cite the exact table and columns used
- Show the SQL query you ran (in a code block)
- Flag any data quality issues or caveats
- Suggest follow-up analyses when appropriate
- For time comparisons, always specify the exact date ranges used

## Critical Data Notes
- BigQuery date columns: Azure uses TIMESTAMP (dateTime), AWS uses DATE (usage_date), GCP uses DATE (dateTime — same name as Azure but DATE type, not TIMESTAMP)
- GCP cost column is `cost` (gross) or `cost_with_credits` (net after credits). Prefer `cost_with_credits` for real spend.
- GCP project columns: `gcp_project_name` (raw GCP name), `cpe_project_name` (business-mapped name). When filtering by project, use `list_dimension_values` to find the exact project name first — never guess or hardcode.
- GCP recommendations are in `reporting_data` dataset, NOT `gcp`
- AWS/Azure recommendations are in SQL Server (`reporting.aws_recommendations`, `reporting.azure_recommendations`), NOT BigQuery
- Always use fully-qualified table names in BQ queries (project.dataset.table)
- SQL Server uses T-SQL syntax: use TOP N instead of LIMIT N
- When writing to files, use the file server tools — never embed large data in responses
"""

    # -- agentic loop ------------------------------------------------------

    async def chat(self, user_message: str) -> str:
        """Process a user message through the agentic tool-calling loop.

        Returns the agent's final text response.
        """
        if not self._client:
            raise RuntimeError("Agent not started. Call start() first.")

        self._history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )

        for round_num in range(MAX_TOOL_ROUNDS):
            response = self._client.models.generate_content(
                model=MODEL,
                contents=self._history,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    tools=(
                        [types.Tool(function_declarations=self._tools)]
                        if self._tools
                        else None
                    ),
                    temperature=0.1,
                ),
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts

            fn_calls = [p for p in parts if p.function_call]

            if not fn_calls:
                # Pure text response — return it
                text = "".join(p.text for p in parts if p.text) or ""
                self._history.append(candidate.content)
                return text

            # --- execute tool calls ---
            # Parallel across servers, sequential within the same server.
            self._history.append(candidate.content)

            fn_responses: list[types.Part] = [None] * len(fn_calls)  # type: ignore[list-item]

            # Group calls by server, preserving original index for ordering
            server_batches: dict[str, list[tuple[int, types.FunctionCall]]] = {}
            for idx, part in enumerate(fn_calls):
                fc = part.function_call
                srv = self._tool_map.get(fc.name)
                server_batches.setdefault(srv, []).append((idx, fc))

            async def _run_batch(server: str | None,
                                 calls: list[tuple[int, types.FunctionCall]]) -> None:
                """Run calls sequentially within one server."""
                for idx, fc in calls:
                    if not server:
                        result_text = f"Unknown tool: {fc.name}"
                    elif server not in self._sessions:
                        result_text = f"Server '{server}' is not connected"
                    else:
                        args = dict(fc.args) if fc.args else {}
                        logger.info(
                            "→ [%s] %s(%s)",
                            server,
                            fc.name,
                            json.dumps(args, default=str)[:300],
                        )
                        try:
                            result = await self._sessions[server].call_tool(
                                fc.name, args
                            )
                            result_text = (
                                result.content[0].text
                                if result.content
                                else "No result"
                            )
                            if result.isError:
                                result_text = f"Tool error: {result_text}"
                        except Exception as exc:
                            result_text = f"Error calling {fc.name}: {exc}"

                        logger.info("← %d chars", len(result_text))

                    fn_responses[idx] = types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_text},
                    )

            # Fan out — each server batch runs concurrently
            await asyncio.gather(
                *(_run_batch(srv, calls) for srv, calls in server_batches.items())
            )

            self._history.append(
                types.Content(role="user", parts=fn_responses)
            )

        return (
            "Reached maximum tool-calling rounds. "
            "Please try a simpler or more specific query."
        )

    def clear_history(self) -> None:
        """Reset conversation history for a new session."""
        self._history.clear()

    @property
    def server_status(self) -> dict[str, bool]:
        """Which servers are connected."""
        return {name: name in self._sessions for name in SERVERS}

    @property
    def tool_count(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )

    agent = FinOpsAgent()
    try:
        print("Starting FinOps Agent...")
        await agent.start()

        status = agent.server_status
        for name, connected in status.items():
            mark = "✓" if connected else "✗"
            print(f"  {mark} {name}")
        print(f"\n{agent.tool_count} tools available. Type 'quit' to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            if user_input.lower() == "clear":
                agent.clear_history()
                print("History cleared.\n")
                continue

            try:
                response = await agent.chat(user_input)
                print(f"\nAgent: {response}\n")
            except Exception as exc:
                logger.exception("Chat error")
                print(f"\nError: {exc}\n")
    finally:
        await agent.stop()
        print("Agent stopped.")


if __name__ == "__main__":
    asyncio.run(main())
