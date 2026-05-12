"""
A2A Server — Exposes the FinOps MCP Agent over the A2A protocol.

The master agent discovers this agent via the Agent Card at:
    GET http://127.0.0.1:9108/.well-known/agent.json

And sends tasks via JSON-RPC at:
    POST http://127.0.0.1:9108/

Run:
    python a2a_server.py
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import uvicorn
from starlette.applications import Starlette

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from agent import FinOpsAgent

logger = logging.getLogger("finops-a2a")

HOST = "127.0.0.1"
PORT = 9108


# ---------------------------------------------------------------------------
# 1. Agent Executor — bridges A2A protocol → your FinOpsAgent
# ---------------------------------------------------------------------------

class FinOpsAgentExecutor(AgentExecutor):
    """Receives A2A tasks, runs them through FinOpsAgent, returns results."""

    def __init__(self, agent: FinOpsAgent) -> None:
        self.agent = agent

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Called by the A2A framework when the master sends a task."""

        # 1. Extract the user's text from the A2A message
        user_message = context.get_user_input()

        if not user_message:
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=Message(
                            role=Role.ROLE_AGENT,
                            parts=[Part(text="No message text received.")],
                            message_id=str(uuid.uuid4()),
                        ),
                    ),
                )
            )
            return

        logger.info("A2A task %s: %s", context.task_id, user_message[:100])

        # 2. Tell the master we're working on it
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )

        # 3. Run the query through your existing FinOpsAgent
        try:
            response_text = await self.agent.chat(user_message)
        except Exception as exc:
            logger.exception("Agent error for task %s", context.task_id)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=Message(
                            role=Role.ROLE_AGENT,
                            parts=[Part(text=f"Agent error: {exc}")],
                            message_id=str(uuid.uuid4()),
                        ),
                    ),
                )
            )
            return

        # 4. Send the completed result back
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_COMPLETED,
                    message=Message(
                        role=Role.ROLE_AGENT,
                        parts=[Part(text=response_text)],
                        message_id=str(uuid.uuid4()),
                    ),
                ),
            )
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Handle cancellation requests."""
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )


# ---------------------------------------------------------------------------
# 2. Agent Card — describes your agent to the master
# ---------------------------------------------------------------------------

AGENT_CARD = AgentCard(
    name="finops_assistant",
    description=(
        "Cloud FinOps cost analysis agent. Queries multi-cloud cost data "
        "(AWS, Azure, GCP) from BigQuery and SQL Server, detects spending "
        "anomalies, forecasts future costs, scores optimization recommendations, "
        "and generates executive reports."
    ),
    version="1.0.0",
    supported_interfaces=[
        AgentInterface(url=f"http://{HOST}:{PORT}", protocol_binding="JSONRPC"),
    ],
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="cost_analysis",
            name="Cloud Cost Analysis",
            description="Query and analyze cloud costs across AWS, Azure, and GCP. Supports breakdowns by service, project, team, and time period.",
            tags=["finops", "cost", "cloud", "aws", "azure", "gcp"],
            examples=[
                "What were the top 5 most expensive GCP services last month?",
                "Show me Azure costs by subscription for Q1 2026",
                "Compare AWS spend this month vs last month",
            ],
        ),
        AgentSkill(
            id="anomaly_detection",
            name="Cost Anomaly Detection",
            description="Detect unusual spending patterns and cost spikes using statistical methods (Z-score, IQR).",
            tags=["finops", "anomaly", "detection", "spending"],
            examples=[
                "Are there any cost anomalies in the last 30 days?",
                "Investigate the spending spike on April 29",
            ],
        ),
        AgentSkill(
            id="forecasting",
            name="Spend Forecasting",
            description="Forecast future cloud spending using linear regression and exponential smoothing with confidence intervals.",
            tags=["finops", "forecast", "prediction", "trend"],
            examples=[
                "Forecast next month's GCP spend",
                "What's the projected AWS cost for Q3?",
            ],
        ),
        AgentSkill(
            id="recommendations",
            name="Optimization Recommendations",
            description="Score and rank cloud optimization recommendations by potential savings, confidence, and implementation effort.",
            tags=["finops", "recommendations", "optimization", "savings"],
            examples=[
                "Show me the top cost optimization recommendations",
                "What Azure reservations should we purchase?",
            ],
        ),
        AgentSkill(
            id="report_generation",
            name="Report Generation",
            description="Generate executive summaries, chargeback reports, and CSV exports of cost data.",
            tags=["finops", "report", "export", "csv"],
            examples=[
                "Generate an executive cost summary for last month",
                "Export GCP costs as CSV",
            ],
        ),
    ],
)


# ---------------------------------------------------------------------------
# 3. Main — wire it all together and start the server
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )

    # Start your existing FinOps agent (connects to 4 MCP servers)
    agent = FinOpsAgent()
    logger.info("Starting FinOps MCP Agent...")
    await agent.start()
    logger.info(
        "Agent ready — %d tools across servers: %s",
        agent.tool_count,
        agent.server_status,
    )

    # Create A2A wiring
    executor = FinOpsAgentExecutor(agent)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=AGENT_CARD,
    )

    # Build the Starlette app with agent card + JSON-RPC routes
    routes = (
        create_agent_card_routes(AGENT_CARD)
        + create_jsonrpc_routes(handler, rpc_url="/")
    )
    starlette_app = Starlette(routes=routes)

    logger.info("A2A server at http://%s:%d", HOST, PORT)
    logger.info(
        "Agent card at http://%s:%d/.well-known/agent.json", HOST, PORT
    )

    # Run with uvicorn
    config = uvicorn.Config(
        starlette_app, host=HOST, port=PORT, log_level="info"
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())