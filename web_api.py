"""
FinOps Web API — FastAPI wrapper around FinOpsAgent with SSE streaming.

Endpoints:
    POST /api/chat          — Send a message, get SSE stream of agent events
    GET  /api/status        — Server/tool status
    POST /api/clear         — Clear conversation history
    GET  /api/health        — Health check

Run:
    uvicorn web_api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from google.genai import types

from agent import FinOpsAgent, MODEL, MAX_TOOL_ROUNDS
import artifacts
import memory
from trace import TurnTrace, ToolCallTrace, TokenUsage

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent
load_dotenv(_project_root / ".env")

logger = logging.getLogger("finops-api")

# ---------------------------------------------------------------------------
# Elicitation block extraction
# ---------------------------------------------------------------------------

import re as _re

_ELICITATION_RE = _re.compile(
    r"```elicitation\s*\n(.*?)\n```",
    _re.DOTALL,
)


def _extract_elicitation(text: str):
    """Extract ALL ```elicitation {...} ``` blocks from LLM output.

    Returns (prose_without_blocks, list_of_elicitation_dicts | None).
    """
    matches = list(_ELICITATION_RE.finditer(text))
    if not matches:
        return text, None

    payloads = []
    for match in matches:
        try:
            payload = json.loads(match.group(1))
            if "type" in payload:
                payloads.append(payload)
        except (json.JSONDecodeError, ValueError):
            continue

    if not payloads:
        return text, None

    # Remove ALL elicitation blocks from prose (reverse order to preserve indices)
    prose = text
    for match in reversed(matches):
        prose = prose[: match.start()] + prose[match.end() :]
    prose = prose.replace("\n\n\n", "\n\n").strip()

    # Return single dict if only one, array if multiple
    return prose, payloads if len(payloads) > 1 else payloads[0]


# ---------------------------------------------------------------------------
# StreamingAgent — extends FinOpsAgent with SSE event yielding
# ---------------------------------------------------------------------------

class StreamingAgent(FinOpsAgent):
    """Extends FinOpsAgent to yield SSE events during the agentic loop."""

    _PERCEPTION_PROMPT = (
        "You are the Perception layer of a FinOps cost-management agent.\n"
        "Decompose the user query into 2-5 ordered, dependency-aware goals.\n"
        "Each goal is a short imperative sentence "
        '(e.g. "Retrieve Azure K8s costs for last month").\n\n'
        "Rules:\n"
        "- Order goals so prerequisites come first.\n"
        "- For SIMPLE queries that need only one step "
        "(greetings, single lookups, basic questions), return an EMPTY goals list.\n"
        "- Do NOT include goals about formatting, presenting, or returning data to the user.\n\n"
        'Return JSON: {"goals": [{"text": "..."}]}'
    )

    _PERCEPTION_REEVAL_PROMPT = (
        "You are the Perception layer of a FinOps cost-management agent.\n"
        "You previously decomposed a query into goals. Review the TOOL RESULTS\n"
        "and determine which goals have been satisfied.\n\n"
        "Rules:\n"
        "- A goal is 'done' if the tool results contain data that fulfills it.\n"
        "- A goal is 'running' if tools were called for it but more steps remain.\n"
        "- A goal is 'pending' if no tools have addressed it yet.\n"
        "- Once marked 'done', a goal stays done forever.\n"
        "- Preserve goal text and order exactly. Do NOT add, remove, or reorder.\n\n"
        'Return JSON: {"goals": [{"id": 0, "text": "...", "status": "done|running|pending"}]}'
    )

    _TOOL_LABELS = {
        "get_table_schema": "Discovering schema",
        "list_dimension_values": "Exploring dimensions",
        "dry_run_query": "Estimating query cost",
        "run_query": "Querying BigQuery",
        "run_multi_cloud_query": "Multi-cloud query",
        "detect_anomalies": "Detecting anomalies",
        "forecast": "Forecasting costs",
        "calculate_growth": "Calculating growth",
        "compare_periods": "Comparing periods",
        "summarize_data": "Summarizing results",
        "format_currency": "Formatting currency",
        "convert_to_chart_data": "Preparing chart",
        "map_services_across_clouds": "Mapping services",
        "cross_examine_recommendations": "Cross-examining",
        "compare_cloud_unit_costs": "Comparing unit costs",
        "generate_what_if_scenario": "Running what-if",
        "score_recommendations": "Scoring recommendations",
        "write_file": "Writing report",
        "export_csv": "Exporting CSV",
    }

    def __init__(self):
        super().__init__()
        self._sessions_history: dict[str, list[types.Content]] = {}
        self._sessions_auto_approve: dict[str, bool] = {}

    # ── Perception: goal decomposition ──────────────────────────────────────

    _JSON_FENCE_RE = _re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", _re.DOTALL)

    def _decompose_goals(self, user_message: str) -> list[dict] | None:
        """Quick structured LLM call to decompose a query into goals.

        Returns a list of goal dicts or None for simple queries.
        """
        try:
            response = self._client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text=f"USER QUERY: {user_message}"
                        )],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=self._PERCEPTION_PROMPT,
                    temperature=0.3,
                    max_output_tokens=1024,
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=128,
                    ),
                ),
            )
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                return None

            # Thinking models put reasoning in thought parts — skip them
            text = ""
            for part in candidate.content.parts:
                if getattr(part, "thought", False):
                    continue
                if part.text:
                    text += part.text

            if not text.strip():
                logger.warning("Perception: model returned no text content")
                return None

            # Try to extract JSON from markdown fences first, then raw
            m = self._JSON_FENCE_RE.search(text)
            json_str = m.group(1) if m else text.strip()
            parsed = json.loads(json_str)

            raw_goals = parsed.get("goals", [])
            if len(raw_goals) < 2:
                return None
            logger.info("Perception: %d goals decomposed", len(raw_goals))
            return [
                {"id": i, "text": g["text"], "status": "pending"}
                for i, g in enumerate(raw_goals)
            ]
        except Exception as exc:
            logger.warning("Perception failed: %s", exc)
            return None

    # ── Perception: re-evaluate goal satisfaction ───────────────────────────

    def _re_evaluate_goals(
        self, goals: list[dict], tool_events: list[dict]
    ) -> list[dict] | None:
        """Re-evaluate which goals are satisfied after a tool round.

        Follows Session 6 pattern: perception is called after each action
        round to track goal satisfaction based on actual tool results,
        rather than advancing linearly.
        """
        try:
            tool_summary_lines = []
            for evt in tool_events:
                name = evt.get("tool", "?")
                chars = evt.get("chars", 0)
                snippet = evt.get("result", "")[:300]
                error = evt.get("error")
                if error:
                    tool_summary_lines.append(f"- {name}: ERROR — {error[:200]}")
                else:
                    tool_summary_lines.append(f"- {name} ({chars} chars): {snippet}")

            prompt = (
                "GOALS:\n"
                + "\n".join(
                    f"  {g['id']}. [{g['status']}] {g['text']}" for g in goals
                )
                + "\n\nTOOL RESULTS:\n"
                + "\n".join(tool_summary_lines)
            )

            response = self._client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=self._PERCEPTION_REEVAL_PROMPT,
                    temperature=0.1,
                    max_output_tokens=512,
                    thinking_config=types.ThinkingConfig(thinking_budget=128),
                ),
            )

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                return None

            text = ""
            for part in candidate.content.parts:
                if getattr(part, "thought", False):
                    continue
                if part.text:
                    text += part.text

            if not text.strip():
                return None

            m = self._JSON_FENCE_RE.search(text)
            json_str = m.group(1) if m else text.strip()
            parsed = json.loads(json_str)

            updated = parsed.get("goals", [])
            if len(updated) != len(goals):
                logger.warning("Perception re-eval: goal count mismatch (%d vs %d)", len(updated), len(goals))
                return None

            # Merge: never un-done a goal
            for i, g in enumerate(goals):
                if g["status"] == "done":
                    continue
                new_status = updated[i].get("status", g["status"])
                if new_status in ("done", "running", "pending"):
                    g["status"] = new_status

            done_count = sum(1 for g in goals if g["status"] == "done")
            logger.info("Perception re-eval: %d/%d goals done", done_count, len(goals))
            return goals

        except Exception as exc:
            logger.warning("Perception re-eval failed: %s", exc)
            return None

    # ── Artifact preview for decision context ───────────────────────────────

    @staticmethod
    def _build_artifact_preview(result_text: str) -> str:
        """Build a structured preview so the decision layer can reason about data.

        Session 6 pattern: the decision layer receives ATTACHED ARTIFACTS with
        actual content (up to 8KB).  We give a structured summary: row count,
        columns, sample rows — enough for the LLM to pick the right next tool.
        """
        try:
            data = json.loads(result_text)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                row_count = len(data)
                columns = list(data[0].keys())
                sample = json.dumps(data[:3], indent=2, default=str)[:1200]
                return (
                    f"{row_count} rows | columns: {', '.join(columns)}\n"
                    f"Sample (first 3 rows):\n{sample}"
                )
        except (json.JSONDecodeError, TypeError, IndexError):
            pass
        # Fallback for non-JSON: first 1000 chars
        return result_text[:1000]

    def _get_history(self, session_id: str) -> list[types.Content]:
        if session_id not in self._sessions_history:
            self._sessions_history[session_id] = []
        return self._sessions_history[session_id]

    def clear_session(self, session_id: str) -> None:
        self._sessions_history.pop(session_id, None)
        self._sessions_auto_approve.pop(session_id, None)
        artifacts.clear()
        memory.clear_session(session_id)

    async def chat_stream(self, user_message: str, session_id: str = "default", cancel_event: asyncio.Event | None = None):
        """Async generator that yields SSE events as the agent works.

        Event types:
            thinking     — agent is processing
            tool_call    — tool invocation (name + args)
            tool_result  — tool response
            text         — final or partial text from Gemini
            error        — something went wrong
            done         — stream complete
        """
        if not self._client:
            yield {"event": "error", "data": json.dumps({"message": "Agent not started"})}
            return

        history = self._get_history(session_id)
        history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )

        # Extract and persist any user preferences from the message
        self._extract_preferences(user_message)

        # Refresh system prompt with latest memory context
        self._system_prompt = await self._build_system_prompt()

        yield {"event": "thinking", "data": json.dumps({"message": "Understanding your question..."})}

        # ── Perception: decompose into goals ──
        goals = self._decompose_goals(user_message)

        if goals:
            yield {
                "event": "plan",
                "data": json.dumps({"goals": goals}),
            }

        for round_num in range(MAX_TOOL_ROUNDS):
            # Check if client disconnected
            if cancel_event and cancel_event.is_set():
                yield {"event": "text", "data": json.dumps({"content": "Request stopped."})}
                yield {"event": "done", "data": json.dumps({"rounds": round_num, "cancelled": True})}
                return

            turn_start = time.time()
            turn = TurnTrace(
                round=round_num + 1,
                active_tools_count=len(self._tools),
                routed_servers=sorted(self._tools_by_server.keys()),
            )

            try:
                response = self._client.models.generate_content(
                    model=MODEL,
                    contents=history,
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
            except Exception as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc)})}
                return

            # --- token tracking ---
            if self._token_tracking:
                turn.tokens = self._extract_usage(response)

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            fn_calls = [p for p in parts if p.function_call]

            # Guard: if model returned completely empty response, skip appending
            # to avoid corrupting history with empty model turns
            has_text = any(p.text for p in parts if p.text)
            if not fn_calls and not has_text:
                # Empty model response — skip this round, retry
                logger.warning("Empty model response (0 parts with content), retrying round %d", round_num + 1)
                continue

            if not fn_calls:
                text = "".join(p.text for p in parts if p.text) or ""
                history.append(candidate.content)

                # Extract structured elicitation block if present
                prose, elicitation = _extract_elicitation(text)

                # Finalize goals only if this is a real final answer,
                # NOT if the agent is asking an elicitation question (goals still pending)
                if goals and not elicitation:
                    for g in goals:
                        g["status"] = "done"
                    yield {"event": "plan", "data": json.dumps({"goals": goals})}

                yield {"event": "text", "data": json.dumps({"content": prose})}
                if elicitation:
                    yield {"event": "elicitation", "data": json.dumps(elicitation)}
                turn.has_text_response = True
                turn.duration_ms = (time.time() - turn_start) * 1000
                if self._token_tracking:
                    self._trace.record_turn(turn)
                done_data = {"rounds": round_num + 1}
                if self._token_tracking:
                    done_data["token_usage"] = self.token_usage
                yield {"event": "done", "data": json.dumps(done_data)}
                return

            # --- execute tool calls with streaming events ---
            history.append(candidate.content)

            fn_responses: list[types.Part] = [None] * len(fn_calls)  # type: ignore[list-item]

            server_batches: dict[str, list[tuple[int, types.FunctionCall]]] = {}
            for idx, part in enumerate(fn_calls):
                fc = part.function_call
                srv = self._tool_map.get(fc.name)
                server_batches.setdefault(srv, []).append((idx, fc))

            # ── Goal progression: mark first pending goal as running ──
            if goals:
                for g in goals:
                    if g["status"] in ("pending", "running"):
                        g["status"] = "running"
                        break
                yield {"event": "plan", "data": json.dumps({"goals": goals})}

            # Collect events from parallel batches via a queue
            event_queue: asyncio.Queue = asyncio.Queue()

            async def _run_batch(server, calls):
                for idx, fc in calls:
                    args = dict(fc.args) if fc.args else {}
                    tool_start = time.time()

                    # Emit tool_call event BEFORE resolving artifacts (keep event small)
                    await event_queue.put({
                        "event": "tool_call",
                        "data": json.dumps({
                            "tool": fc.name,
                            "server": server or "unknown",
                            "args": {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v) for k, v in args.items()},
                        }, default=str),
                    })

                    # Resolve artifact references in tool arguments
                    for key, val in args.items():
                        if isinstance(val, str) and val.startswith("art:") and artifacts.exists(val):
                            args[key] = artifacts.get_text(val)

                    error_msg = None
                    if not server or server not in self._sessions:
                        result_text = f"Server '{server}' not available"
                        error_msg = result_text
                    else:
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
                                error_msg = result_text
                                result_text = f"Tool error: {result_text}"
                        except Exception as exc:
                            result_text = f"Error: {exc}"
                            error_msg = result_text

                    truncated = len(result_text) > 2000
                    display_text = (
                        result_text[:2000] + "..."
                        if truncated
                        else result_text
                    )

                    # Store large results as artifacts to keep LLM context lean
                    # Build a structured preview (Session 6: decision sees attached artifacts)
                    llm_result_text = result_text
                    art_id = None
                    if len(result_text) > 4000:
                        art_id = artifacts.put(
                            result_text,
                            source=f"{server}:{fc.name}",
                            descriptor=f"{fc.name}({json.dumps(args, default=str)[:80]}) → {len(result_text)} chars",
                        )
                        preview = StreamingAgent._build_artifact_preview(result_text)
                        llm_result_text = (
                            f"[Artifact {art_id} stored — {len(result_text)} chars]\n"
                            f"{preview}\n\n"
                            f"Full data is stored. To analyze it, call the appropriate tool "
                            f'with artifact_id="{art_id}" (do NOT pass data_json). '
                            f"Artifact references in tool arguments are resolved automatically."
                        )

                    turn.tool_calls.append(ToolCallTrace(
                        tool=fc.name,
                        server=server or "unknown",
                        args=args,
                        result_chars=len(result_text),
                        truncated=truncated,
                        error=error_msg,
                        artifact_id=art_id,
                        duration_ms=(time.time() - tool_start) * 1000,
                    ))

                    await event_queue.put({
                        "event": "tool_result",
                        "data": json.dumps({
                            "tool": fc.name,
                            "result": display_text,
                            "full_result": result_text if truncated else None,
                            "chars": len(result_text),
                            "artifact_id": art_id,
                        }),
                    })

                    fn_responses[idx] = types.Part.from_function_response(
                        name=fc.name,
                        response={"result": llm_result_text},
                    )

            # Fan out — each server batch runs concurrently
            await asyncio.gather(
                *(_run_batch(srv, calls) for srv, calls in server_batches.items())
            )

            # Drain queued events and collect tool results for perception
            round_tool_events = []
            while not event_queue.empty():
                evt = await event_queue.get()
                yield evt
                # Collect tool_result events for perception re-evaluation
                if isinstance(evt, dict) and evt.get("event") == "tool_result":
                    try:
                        round_tool_events.append(json.loads(evt["data"]))
                    except (json.JSONDecodeError, KeyError):
                        pass

            # ── Perception re-evaluation: assess goal satisfaction ──
            if goals:
                self._re_evaluate_goals(goals, round_tool_events)
                yield {"event": "plan", "data": json.dumps({"goals": goals})}

            history.append(
                types.Content(role="user", parts=fn_responses)
            )

            turn.duration_ms = (time.time() - turn_start) * 1000
            if self._token_tracking:
                self._trace.record_turn(turn)

            yield {
                "event": "thinking",
                "data": json.dumps({"message": f"Analyzing results (round {round_num + 2})..."}),
            }

        yield {
            "event": "text",
            "data": json.dumps({"content": "Reached maximum tool-calling rounds. Please try a simpler query."}),
        }
        yield {"event": "done", "data": json.dumps({"rounds": MAX_TOOL_ROUNDS})}


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_agent: StreamingAgent | None = None


# ---------------------------------------------------------------------------
# Lifespan — start/stop agent with the server
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )
    _agent = StreamingAgent()
    await _agent.start()
    logger.info("Agent started — %d tools", _agent.tool_count)
    yield
    await _agent.stop()
    _agent = None
    logger.info("Agent stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FinOps MCP Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})
    return {
        "servers": _agent.server_status,
        "tool_count": _agent.tool_count,
        "model": MODEL,
    }


@app.post("/api/chat")
async def chat(request: Request):
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")
    if not message:
        return JSONResponse(status_code=400, content={"error": "Empty message"})

    # Check for "Accept all for session" response and set flag
    if message.lower() in ("accept all for session", "accept all"):
        _agent._sessions_auto_approve[session_id] = True

    # Inject auto-approve context so the LLM knows to skip dry-runs
    effective_message = message
    if _agent._sessions_auto_approve.get(session_id, False):
        effective_message = f"[auto_approve_queries=true]\n{message}"

    cancel = asyncio.Event()

    async def event_generator():
        async for event in _agent.chat_stream(effective_message, session_id=session_id, cancel_event=cancel):
            if await request.is_disconnected():
                cancel.set()
                return
            yield event

    return EventSourceResponse(event_generator())


@app.post("/api/clear")
async def clear(request: Request):
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    session_id = body.get("session_id", "default") if body else "default"
    _agent.clear_session(session_id)
    return {"status": "cleared"}


@app.get("/api/tokens")
async def tokens():
    """Get current session token usage breakdown."""
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})
    return _agent.token_usage


@app.post("/api/tokens/toggle")
async def toggle_tokens(request: Request):
    """Enable or disable token tracking. Body: {"enabled": true/false}"""
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})
    body = await request.json()
    enabled = body.get("enabled", True)
    _agent.set_token_tracking(bool(enabled))
    return {"tracking_enabled": _agent._token_tracking}


# ---------------------------------------------------------------------------
# File download — serves exported reports from the sandbox
# ---------------------------------------------------------------------------

_REPORTS_DIR = _project_root / "reports"

_SAFE_FILENAME_RE = __import__("re").compile(r"^[\w\-./]+$")


@app.get("/api/reports/{filename:path}")
async def download_report(filename: str):
    """Serve a file from the reports sandbox for browser download."""
    if not _SAFE_FILENAME_RE.match(filename):
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})

    filepath = (_REPORTS_DIR / filename).resolve()
    # Prevent directory traversal
    if _REPORTS_DIR.resolve() not in filepath.parents and filepath != _REPORTS_DIR.resolve():
        return JSONResponse(status_code=403, content={"error": "Access denied"})
    if not filepath.exists() or not filepath.is_file():
        return JSONResponse(status_code=404, content={"error": "File not found"})

    return FileResponse(
        path=filepath,
        filename=filepath.name,
        media_type="application/octet-stream",
    )
