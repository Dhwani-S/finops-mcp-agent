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
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from google.genai import types

from agent import FinOpsAgent, MODEL, MAX_TOOL_ROUNDS

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent
load_dotenv(_project_root / ".env")

logger = logging.getLogger("finops-api")


# ---------------------------------------------------------------------------
# StreamingAgent — extends FinOpsAgent with SSE event yielding
# ---------------------------------------------------------------------------

class StreamingAgent(FinOpsAgent):
    """Extends FinOpsAgent to yield SSE events during the agentic loop."""

    async def chat_stream(self, user_message: str):
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

        self._history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )

        yield {"event": "thinking", "data": json.dumps({"message": "Understanding your question..."})}

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
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
            except Exception as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc)})}
                return

            candidate = response.candidates[0]
            parts = candidate.content.parts
            fn_calls = [p for p in parts if p.function_call]

            if not fn_calls:
                text = "".join(p.text for p in parts if p.text) or ""
                self._history.append(candidate.content)
                yield {"event": "text", "data": json.dumps({"content": text})}
                yield {"event": "done", "data": json.dumps({"rounds": round_num + 1})}
                return

            # --- execute tool calls with streaming events ---
            self._history.append(candidate.content)

            fn_responses: list[types.Part] = [None] * len(fn_calls)  # type: ignore[list-item]

            server_batches: dict[str, list[tuple[int, types.FunctionCall]]] = {}
            for idx, part in enumerate(fn_calls):
                fc = part.function_call
                srv = self._tool_map.get(fc.name)
                server_batches.setdefault(srv, []).append((idx, fc))

            # Collect events from parallel batches via a queue
            event_queue: asyncio.Queue = asyncio.Queue()

            async def _run_batch(server, calls):
                for idx, fc in calls:
                    args = dict(fc.args) if fc.args else {}
                    await event_queue.put({
                        "event": "tool_call",
                        "data": json.dumps({
                            "tool": fc.name,
                            "server": server or "unknown",
                            "args": args,
                        }, default=str),
                    })

                    if not server or server not in self._sessions:
                        result_text = f"Server '{server}' not available"
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
                                result_text = f"Tool error: {result_text}"
                        except Exception as exc:
                            result_text = f"Error: {exc}"

                    # Truncate for SSE display (full result goes to Gemini)
                    display_text = (
                        result_text[:2000] + "..."
                        if len(result_text) > 2000
                        else result_text
                    )

                    await event_queue.put({
                        "event": "tool_result",
                        "data": json.dumps({
                            "tool": fc.name,
                            "result": display_text,
                            "chars": len(result_text),
                        }),
                    })

                    fn_responses[idx] = types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_text},
                    )

            # Fan out — each server batch runs concurrently
            await asyncio.gather(
                *(_run_batch(srv, calls) for srv, calls in server_batches.items())
            )

            # Drain all queued events
            while not event_queue.empty():
                yield await event_queue.get()

            self._history.append(
                types.Content(role="user", parts=fn_responses)
            )

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
    if not message:
        return JSONResponse(status_code=400, content={"error": "Empty message"})

    async def event_generator():
        async for event in _agent.chat_stream(message):
            yield event

    return EventSourceResponse(event_generator())


@app.post("/api/clear")
async def clear():
    if not _agent:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})
    _agent.clear_history()
    return {"status": "cleared"}


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
