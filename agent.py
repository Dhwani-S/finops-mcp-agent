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
_PROMPT_FILE = _project_root / "prompts" / "system_prompt.md"
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

# Max chars of tool output to keep in conversation history.
# Large BQ results (500 rows of JSON) pollute context and cause hallucinations.
_MAX_TOOL_RESULT_CHARS = 4000


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
        """Load all MCP resources and compose the system prompt.
        
        Caps each resource at 2000 chars to prevent prompt bloat.
        """
        resource_sections: list[str] = []
        _MAX_RESOURCE_CHARS = 2000

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
                            if len(text) > _MAX_RESOURCE_CHARS:
                                text = text[:_MAX_RESOURCE_CHARS] + "\n[... truncated]"
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

        template = _PROMPT_FILE.read_text(encoding="utf-8")
        return template.replace("{{RESOURCES_BLOCK}}", resources_block)

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

                    # Truncate large results to prevent context window pollution
                    if len(result_text) > _MAX_TOOL_RESULT_CHARS:
                        truncated = result_text[:_MAX_TOOL_RESULT_CHARS]
                        # Try to count rows for a helpful summary
                        try:
                            parsed = json.loads(result_text)
                            if isinstance(parsed, list):
                                row_count = len(parsed)
                                truncated += (
                                    f"\n\n[TRUNCATED — showing first ~{_MAX_TOOL_RESULT_CHARS} chars "
                                    f"of {row_count} rows. Use the data above for analysis. "
                                    f"Do NOT re-fetch — you already have the data.]"
                                )
                            else:
                                truncated += "\n\n[TRUNCATED — result too large to show in full.]"
                        except (json.JSONDecodeError, TypeError):
                            truncated += "\n\n[TRUNCATED — result too large to show in full.]"
                        result_text = truncated

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
