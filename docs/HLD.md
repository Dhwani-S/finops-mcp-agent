# High-Level Design (HLD)

## Spec-Compliant MCP Apps Architecture for Agentic Internal Developer Platform

**Version:** 1.0  
**Date:** May 2026  
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [Architecture Overview](#4-architecture-overview)
5. [Component Design](#5-component-design)
6. [Communication & Protocol Design](#6-communication--protocol-design)
7. [Data Flow](#7-data-flow)
8. [Security Architecture](#8-security-architecture)
9. [Context Management & Tool Optimization](#9-context-management--tool-optimization)
10. [Deployment Architecture](#10-deployment-architecture)
11. [Technology Stack](#11-technology-stack)
12. [Non-Functional Requirements](#12-non-functional-requirements)

---

## 1. Executive Summary

This document describes the high-level architecture of an **Agentic Internal Developer Platform (IDP)** that brings enterprise portal services directly into the developer's IDE. The platform uses a multi-agent orchestration pattern combining **MCP (Model Context Protocol)** for tool access and UI rendering, **A2A (Agent-to-Agent)** for inter-agent communication, and **MCP Apps** for interactive, portal-like UI experiences embedded in the IDE via sandboxed iframes.

---

## 2. Problem Statement

### The Chicken-Egg Problem

The organization operates an Internal Developer Portal (IDP) where departments (DLT, Infrastructure, FinOps, etc.) offer self-service capabilities. Two interdependent problems stalled its growth:

| Stakeholder | Problem |
|---|---|
| **Developers** | Refuse to leave their IDE to use the portal. Adoption remains low because the context switch is too costly. |
| **Leadership** | Won't invest in new portal features due to low adoption metrics. |

### Secondary Challenges

- **No unified agent architecture** — Departments built agents independently with no governance, guardrails, or communication standards.
- **Skill gaps** — Teams lack expertise to build agentic systems, implement vector search, or manage LLM context.
- **Siloed contexts** — Each agent manages its own knowledge base, making cross-department routing unreliable.
- **Centralized auth missing** — No unified authorization model across agents.
- **Context pollution** — Thousands of tools across departments overwhelm LLM context windows.

---

## 3. Solution Overview

### Core Idea

Bring the IDP **inside the IDE** by:

1. Exposing department services as **MCP-accessible agents** behind a unified supervisor.
2. Rendering familiar portal UI inside the IDE using **MCP Apps** (sandboxed iframes) — developers see the same forms and dashboards they'd see in the portal.
3. Providing a **shared Context Lake** and **Registry** so the supervisor can intelligently route requests without teams needing to build their own search infrastructure.

### Design Principles

| Principle | Implementation |
|---|---|
| **Human-In-The-Loop (HITL)** | MCP Elicitation for approval gates on non-idempotent actions |
| **Sandboxed isolation** | MCP Apps run in iframes with deny-by-default CSP; all communication via postMessage |
| **Protocol separation** | IDE speaks MCP only; agents speak A2A; bridge server translates |
| **Namespace isolation** | Context Lake provides public (routing) and private (agent-scoped) namespaces |
| **No privilege escalation** | 3LO Auth Code + PKCE; Host controls all capability access |

---

## 4. Architecture Overview

### System Context

```
             ┌─────────────────────────────────────────────────────────────────┐
             │        Async Event Bus (Pub/Sub / Kafka)                        │
             │   [Topic]  subscribe(task_complete, status_update)              │
             └─────────────────────────┬───────────────────────────────────────┘
                          push notif ↓ │ ▲ publish(task_complete)
┌───────────────────────┐            ┌─┘ │
│  VS Code (Host)       │            │    │
│  • Copilot Chat (LLM) │         ┌──▼───┴────────────────┐
│  • Built-in MCP Client│──MCP───▶│  MCP Bridge Server   │
│  • MCP App Renderer   │◀────────│  (mcp_server.py)     │
│    (sandboxed iframe) │         │  • ask_master() tool  │
│                       │         │  • elicitation()      │
│  ┌─────────────────┐  │         │  • registerAppResource│
│  │ MCP App (iframe) │ │         └──────────┬───────────┘
│  │ postMessage ↔   │──┤                    │
│  └─────────────────┘  │                    │ A2A message/send
└───────────────────────┘                    │ (JSON-RPC / HTTP)
                                             ▼
                              ┌══════════════════════════════════════┐
                              ║  CUSTOM IDP AGENTIC PLATFORM        ║
                              ║                                      ║
                              ║  ┌────────────────┐  ┌────────────┐ ║
                              ║  │ Supervisor     │  │Context Lake│ ║
                              ║  │ • LLM Router   │◀▶│• Vector DB │ ║
                              ║  │ • Judge        │  │• 🔓 Public │ ║
                              ║  └───────┬────────┘  │• 🔒 Private│ ║
                              ║          │ A2A       └────────────┘ ║
                              ║          ▼           ┌────────────┐ ║
                              ║  ┌────────────────┐  │ Registry   │ ║
                              ║  │ Sub-agents ────┼──┼───▶ Event  │ ║
                              ║  │ (DLT, Infra,   │◀▶│   Bus pub  │ ║
                              ║  │  FinOps, etc.) │  │• Agents    │ ║
                              ║  └───────┬────────┘  │• MCP Srvrs │ ║
                              ║          │           │• Skills    │ ║
                              ╚══════════╪═══════════╧════════════╝
                                         │ MCP tools/call
                                         ▼
                              ┌──────────────────────┐
                              │ Backend MCP Servers   │
                              │ (per department)      │
                              │         │ API         │
                              │         ▼             │
                              │ Backend Systems       │
                              └──────────────────────┘
```

### Key Architectural Decisions

| Decision | Rationale |
|---|---|
| MCP Bridge as protocol translator | IDE speaks MCP only; Supervisor speaks A2A only. The bridge translates between them without coupling either side. |
| Context Lake with namespaces | Solves both routing ambiguity (public namespace) and team data sovereignty (private namespace) while saving teams the effort of building their own vector search. |
| Registry for dynamic discovery | Supervisor doesn't load all agents at startup. It queries the registry on-the-go based on the user's request. Scales to hundreds of department agents. |
| MCP Apps for UI | Psychological familiarity — developers see the same forms and dashboards they associate with the portal, but inside their IDE. Event-driven interaction (click to act, no extra prompts). |

---

## 5. Component Design

### 5.1 VS Code (Host)

The IDE is the user's entry point. All components listed below are **built into VS Code** — developers do not build or configure them:

| Component | Role |
|---|---|
| **Copilot Chat** | Built-in LLM (Claude/GPT) that processes user queries and decides which MCP tools to call |
| **MCP Client** | Built-in protocol client that connects to MCP servers defined in `.vscode/mcp.json` |
| **MCP App Renderer** | Renders MCP Apps in sandboxed iframes when a tool declares `_meta.ui.resourceUri` |

**Configuration** (the only thing developers touch):
```json
// .vscode/mcp.json
{
  "servers": {
    "idp-platform": {
      "type": "http",
      "url": "http://<bridge-host>:8989/mcp"
    }
  }
}
```

### 5.2 MCP Bridge Server (`mcp_server.py`)

The **protocol translation layer** between the IDE (MCP) and the platform (A2A).

| Responsibility | Detail |
|---|---|
| **MCP ↔ A2A translation** | Receives MCP `tools/call`, internally sends A2A `message/send` to Supervisor |
| **MCP Elicitation** | Translates A2A `input_required` states into VS Code's native `ctx.elicit()` dialogs (approve/deny) |
| **UI Resource Serving** | `registerAppResource()` serves bundled HTML for MCP Apps; referenced via `_meta.ui.resourceUri` in tool metadata |
| **HITL bridge** | When Supervisor's sub-agent needs approval, the bridge presents it as a native VS Code dialog and sends the decision back via A2A resume |

**Key tool:**
```python
@mcp.tool()
async def ask_master(query: str, ctx: Context) -> str:
    """Routes user query to the Supervisor Agent via A2A."""
    client = await ClientFactory.connect(MASTER_URL)
    async for event in client.send_message(Message(parts=[TextPart(text=query)])):
        # Handle task states: completed, input_required, failed
        ...
```

### 5.3 Supervisor Agent

The central orchestrator of the platform.

| Sub-component | Role |
|---|---|
| **LLM Router** | Uses the LLM + Context Lake semantic search + Registry lookup to determine which sub-agent should handle a request |
| **Judge** | Monitors conversation flow for loops (agent calling itself), quality degradation, and cross-verifies that responses match the original intent |
| **SupervisorGateway** | HITL state machine that intercepts `input_required` from sub-agents, saves state, and bubbles approval requests up to the bridge |

**Routing logic:**
1. Parse user intent from natural language
2. Query Context Lake (public namespace) for semantic matches against department documentation
3. Query Registry for matching agents, skills, and Agent Cards
4. Route to the best-matched sub-agent via A2A `message/send`
5. If ambiguous, ask user for clarification via elicitation

### 5.4 Context Lake

A shared **vector database** with namespace-based access control.

```
┌──────────────────────────────────────┐
│            Context Lake              │
├──────────────────────────────────────┤
│  🔓 PUBLIC NAMESPACE                │
│  • Department wiki docs              │
│  • Service descriptions              │
│  • Capability summaries              │
│  • Use-case examples                 │
│  Purpose: Help Supervisor route      │
│  accurately when agent cards alone   │
│  are insufficient (e.g., DLT vs      │
│  Infra overlap)                      │
├──────────────────────────────────────┤
│  🔒 PRIVATE NAMESPACE (per team)    │
│  • Agent conversation contexts       │
│  • Internal knowledge bases          │
│  • Proprietary data references       │
│  Purpose: Teams get managed vector   │
│  search without building their own   │
│  infra. Data stays scoped.           │
└──────────────────────────────────────┘
```

**Why teams adopt it:** They don't need to implement vector search or semantic search themselves. They use the platform's Context Lake service for their agents while controlling what stays private vs. what helps the Supervisor route.

### 5.5 Registry

A **dynamic service catalog** for agents, MCP servers, skills, and Agent Cards.

| Feature | Detail |
|---|---|
| Agent registration | Teams register their agents with metadata (skills, capabilities, input/output modes) |
| MCP server catalog | Tracks all department MCP servers and their tools |
| On-the-go discovery | Supervisor queries the registry at runtime — no static configuration needed |
| Agent Cards | Standard A2A Agent Cards stored and served from registry |

### 5.6 Sub-agents (Department Agents)

Each department operates one or more sub-agents. Example — **FinOps Agent**:

| Aspect | Detail |
|---|---|
| **LLM** | Vertex AI Gemini 2.5 Pro |
| **MCP Servers** | 4 stdio servers: BigQuery, SQL Server, Analytics, File |
| **Tool count** | 13+ tools across servers |
| **A2A exposure** | Port 9108, Agent Card at `/.well-known/agent-card.json` |
| **Skills** | Cost analysis, anomaly detection, forecasting, recommendations, report generation |
| **Tool routing** | Keyword-based routing to limit active tools per query (reduces context) |
| **HITL** | Query cost confirmation via dry-run before BigQuery execution |

**Sub-agent MCP server architecture (FinOps example):**

```
FinOps Agent (Gemini)
    ├── BQ Server (stdio)
    │   ├── run_bq_query         — Read-only with SQL guardrails
    │   ├── dry_run_bq_query     — Cost estimation before execution
    │   ├── bq_list_dimension_values — Schema discovery
    │   └── 9 resources          — Table schemas, query patterns
    │
    ├── SQL Server (stdio)
    │   ├── run_sql_query         — Azure/AWS recommendations, K8s costs
    │   ├── get_table_schema      — Dynamic schema discovery
    │   └── sql_list_dimension_values
    │
    ├── Analytics Server (stdio)
    │   ├── detect_anomalies      — Z-score, IQR statistical methods
    │   ├── forecast              — Linear regression, exponential smoothing
    │   ├── calculate_growth      — Period-over-period comparison
    │   ├── score_recommendations — Savings/confidence/effort scoring
    │   └── summarize_data        — Large result set compression
    │
    └── File Server (stdio)
        ├── write_file            — Sandboxed report output
        ├── export_csv            — Data export
        ├── read_file             — Report retrieval
        ├── list_files            — Available reports
        └── format_currency       — Display formatting
```

### 5.7 MCP Apps (Rendered UI)

Interactive HTML interfaces rendered inside the IDE as sandboxed iframes.

| Aspect | Detail |
|---|---|
| **Purpose** | Provide familiar portal-like UI so developers feel comfortable (psychological familiarity with calendars, forms, dashboards) |
| **Registration** | Tool declares `_meta.ui.resourceUri` pointing to a `ui://` resource; Bridge serves HTML via `registerAppResource()` |
| **Rendering** | VS Code's built-in renderer fetches the HTML resource and displays it in a sandboxed iframe |
| **Communication** | `App` class SDK: `app.callServerTool()` sends via postMessage → VS Code → MCP → Bridge |
| **Security** | Sandboxed iframe, deny-by-default CSP, no parent DOM access |
| **Interaction** | Event-driven — click a button, submit a form, and it triggers tool calls automatically. No need to type additional prompts. |

---

## 6. Communication & Protocol Design

### 6.1 Protocol Map

```
User ──NL──▶ VS Code
VS Code ──MCP tools/call──▶ MCP Bridge
MCP Bridge ──A2A message/send──▶ Supervisor
Supervisor ──A2A message/send──▶ Sub-agent
Sub-agent ──MCP tools/call──▶ Backend MCP Server
Backend MCP Server ──API──▶ Backend Systems
MCP App ──postMessage──▶ VS Code ──MCP──▶ Bridge  (no direct bypass)
MCP Bridge ──MCP Elicitation──▶ IDM (auth gates)
Sub-agent ──publish──▶ Event Bus (async task completion)
Event Bus ──subscribe──▶ Supervisor ──push notification──▶ Bridge ──▶ IDE
```

### 6.2 Protocol Comparison

| | MCP | A2A |
|---|---|---|
| **Wire format** | JSON-RPC 2.0 | JSON-RPC 2.0 |
| **Methods** | `tools/call`, `tools/list`, `resources/read` | `message/send`, `tasks/get`, `tasks/cancel` |
| **Data model** | Tools, Resources, Prompts | Tasks, Messages, Parts, Artifacts |
| **Discovery** | Server declares `capabilities` on `initialize` | Agent Card at `/.well-known/agent-card.json` |
| **Who calls** | Host (IDE) calls server tools | Agent sends messages to another agent |
| **Transport** | stdio, SSE, Streamable HTTP | HTTP |

### 6.3 Why Both Protocols?

- **MCP** is the only protocol VS Code's built-in client supports. It's designed for tool/resource access.
- **A2A** is designed for agent-to-agent communication with task lifecycle (submitted → working → input_required → completed → failed).
- The **MCP Bridge** translates between them so neither side needs to know the other's protocol.

### 6.4 Sequence Flow — Full Request Lifecycle

```
Developer        VS Code         MCP Bridge      Supervisor      Sub-agent       Backend MCP
   │                │                │               │               │               │
   │─ NL request ──▶│                │               │               │               │
   │                │─MCP tools/call▶│               │               │               │
   │                │                │─A2A msg/send─▶│               │               │
   │                │                │               │─query CtxLake │               │
   │                │                │               │─query Registry│               │
   │                │                │               │─A2A msg/send─▶│               │
   │                │                │               │               │─MCP tools/call▶│
   │                │                │               │               │◀──tool result──│
   │                │                │               │◀──A2A result──│               │
   │                │                │◀──A2A result──│               │               │
   │                │◀──MCP result───│               │               │               │
   │                │                │               │               │               │
   │                │─pre-fetch UI──▶│(appResource)  │               │               │
   │                │◀──HTML─────────│               │               │               │
   │                │─render iframe──│               │               │               │
   │◀─display form──│                │               │               │               │
   │                │                │               │               │               │
   │─click button──▶│(postMessage)   │               │               │               │
   │                │─MCP tools/call▶│               │               │               │
   │                │                │─A2A──────────▶│──────────────▶│──────────────▶│
   │                │                │◀──────────────│◀──────────────│◀──────────────│
   │                │◀──fresh data───│               │               │               │
   │◀─update UI─────│                │               │               │               │
```

---

## 7. Data Flow

### 7.1 Request Data Flow

1. **User input** (natural language) → VS Code Copilot Chat
2. **Copilot LLM** decides to call `ask_master` tool → MCP `tools/call` to Bridge
3. **Bridge** translates to A2A `message/send` → Supervisor
4. **Supervisor** queries Context Lake (semantic search) + Registry (agent lookup) → routes to sub-agent via A2A
5. **Sub-agent** calls backend MCP servers (BigQuery, SQL Server, APIs) → gets data
6. **Response** flows back: Sub-agent → A2A → Supervisor → A2A → Bridge → MCP → VS Code → displayed to user

### 7.2 MCP App Interaction Data Flow

1. **Bridge** returns tool result with `_meta.ui.resourceUri` → VS Code pre-fetches HTML from `registerAppResource()`
2. **VS Code** renders HTML in sandboxed iframe, pushes initial tool result via `app.ontoolresult`
3. **User** interacts with form → `app.callServerTool()` → postMessage → VS Code → MCP `tools/call` → Bridge → A2A → sub-agent
4. **Result** flows back same path → VS Code pushes fresh data to iframe

### 7.3 HITL Approval Flow

1. **Sub-agent** returns `input_required` state via A2A (e.g., "deploy will cost $X, approve?")
2. **Supervisor's SupervisorGateway** intercepts, saves HITL state, bubbles up to Bridge
3. **Bridge** translates to MCP Elicitation: `ctx.elicit("Approve deployment?", ApprovalSchema)`
4. **VS Code** shows native approve/deny dialog to user
5. **User decision** flows back: VS Code → MCP → Bridge → A2A resume message → Supervisor → Sub-agent

### 7.4 Auth Gate Flow

1. **Sub-agent** returns `auth_required` state via A2A (e.g., "need BigQuery credentials for this project")
2. **Supervisor's SupervisorGateway** intercepts the auth requirement
3. **Bridge** initiates **3LO / Authorization Code + PKCE** flow → IDM Provider issues OAuth challenge
4. **VS Code** shows OAuth consent dialog to user
5. **Token returned** → Bridge → A2A resume message → Supervisor → Sub-agent retries the operation with the issued token

> **Key distinction:** `input_required` is for human judgment gates (approve/deny a destructive action). `auth_required` is for credential acquisition (OAuth token needed to access a backend system). Both bubble up through the same Bridge path but trigger different IDE experiences.

### 7.5 Async Event Flow (Pub/Sub)

For long-running operations (Infra provisioning, DLT pipeline runs, batch cost analysis):

1. **Sub-agent** starts a long-running operation and returns an immediate acknowledgment
2. When the operation completes, the sub-agent **publishes** a `task_complete` or `status_update` event to the Async Event Bus (Pub/Sub / Kafka)
3. **Supervisor subscribes** to relevant topics and receives the completion event
4. Supervisor routes the notification through **Bridge → MCP → IDE** as a push notification
5. **VS Code** surfaces the notification to the developer (e.g., "Your Terraform apply completed successfully")

This decouples the user's IDE session from backend execution time — the developer can continue working and receives notifications asynchronously.

### 7.6 Data Storage

| Store | Purpose | Scope |
|---|---|---|
| **Context Lake (Vector DB)** | Semantic search for routing + agent knowledge | Platform-wide (namespaced) |
| **Registry** | Agent/MCP server/skill catalog | Platform-wide |
| **Redis** | Token caching, session state | Platform-wide |
| **Async Event Bus (Pub/Sub / Kafka)** | Async task completion events, status updates, push notifications | Platform-wide |
| **BigQuery** | Cloud cost data (GCP, AWS, Azure) | FinOps sub-agent |
| **SQL Server** | Recommendations, K8s costs | FinOps sub-agent |
| **Filesystem** | Generated reports (sandboxed) | FinOps sub-agent |

---

## 8. Security Architecture

### 8.1 Authentication & Authorization

| Mechanism | Layer | Detail |
|---|---|---|
| **3LO: Auth Code + PKCE** | IDE ↔ IDM | Delegated token flow; IDE and MCP Bridge handle the OAuth exchange |
| **MCP Elicitation** | Bridge ↔ VS Code | User approvals for non-idempotent actions (deploy, delete, cost queries) |
| **Namespace ACL** | Context Lake | Teams control public vs. private visibility of their data |
| **Agent Card auth** | A2A | Sub-agents can declare auth requirements in their Agent Cards |

### 8.2 MCP Apps Security

| Control | Implementation |
|---|---|
| **Sandboxed iframe** | App cannot access parent DOM, cookies, or local storage |
| **postMessage channel** | All communication goes through VS Code host; no direct network access to agents |
| **Deny-by-default CSP** | External resources blocked unless explicitly allowlisted via `_meta.ui.csp` |
| **Host-controlled capabilities** | VS Code decides which tools the app can call; can restrict tool access per app |
| **No privilege escalation** | App runs with the user's permissions only; cannot elevate |

### 8.3 Data Security (Sub-agent Level)

| Control | Implementation |
|---|---|
| **SQL guardrails** | Blocked DML/DDL keywords (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE) |
| **Bytes-billed caps** | BigQuery queries capped at 500 GB |
| **Query cost confirmation** | Dry-run before execution; user must approve estimated cost |
| **Result truncation** | Tool output capped at 4,000 characters to prevent context pollution |
| **Sandboxed file I/O** | File server restricted to designated report directory |
| **Credential isolation** | Each MCP server has its own credentials; no cross-server access |

---

## 9. Context Management & Tool Optimization

### 9.1 Problem

With hundreds of tools across department agents, feeding all tools to an LLM context window is impractical. It causes:
- Token waste (tool descriptions consume context)
- Routing confusion (LLM picks wrong tools)
- Increased latency and cost

### 9.2 Advanced MCP Patterns (Sub-agent Level)

Based on [Anthropic's Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use):

| Pattern | How it's used |
|---|---|
| **Tool Search Tool** | Agent uses a search tool to discover relevant tools from thousands without loading all into context. Only matched tools are injected. |
| **Programmatic Tool Calling** | Agent invokes tools in a code execution environment, reducing impact on the model's context window. |
| **Tool Use Examples** | Standard examples demonstrating how to chain tools effectively (e.g., "query → forecast → chart"). Reduces hallucinated tool usage. |

### 9.3 Token Caching Strategy

Empirical finding: **Token caching and Tool Search Tool conflict.** When tool search dynamically injects different tool sets per turn, cached prompts are invalidated every turn. Disabling tool search and using a static tool set allows cache to persist across turns — significantly reducing token usage and latency.

**Recommendation:** Use tool search for agents with >50 tools. For agents with <50 tools, use static tool sets with caching enabled.

### 9.4 Keyword-Based Tool Routing (FinOps Example)

Before sending to the LLM, the agent pre-filters tools by keyword matching:

```python
_TOOL_ROUTES = [
    ({"report", "file", "export", "csv"}, {"file"}),
    ({"gcp", "bigquery", "bq"},           {"bq", "analytics"}),
    ({"azure", "aws", "recommendation"},  {"sql", "analytics"}),
    ({"anomaly", "forecast", "trend"},    {"bq", "sql", "analytics"}),
]
```

Only tools from matched servers are included in the LLM call. This reduces context by 60-80% per turn.

### 9.5 Result Truncation

Large query results (BigQuery can return 500 rows of JSON) are truncated at 4,000 characters. For detailed analysis, results are piped through a `summarize_data` tool that extracts statistics and top/bottom items before entering context.

---

## 10. Deployment Architecture

### 10.1 Component Deployment

| Component | Deployment | Port | Scaling |
|---|---|---|---|
| **MCP Bridge** | Container | 8989 | Stateless — horizontal |
| **Supervisor Agent** | Container | 9100 | Single instance (session state) |
| **FinOps Sub-agent** | Container | 9108 (A2A) | Stateless — horizontal |
| **FinOps Web API** | Container | 8000 | Stateless — horizontal |
| **FinOps React Frontend** | Static (Vite build) | 3000 | CDN/Static hosting |
| **BQ MCP Server** | Subprocess (stdio) | N/A | Managed by agent process |
| **SQL MCP Server** | Subprocess (stdio) | N/A | Managed by agent process |
| **Analytics MCP Server** | Subprocess (stdio) | N/A | Managed by agent process |
| **File MCP Server** | Subprocess (stdio) | N/A | Managed by agent process |
| **Context Lake** | Managed service | — | Scales with data |
| **Registry** | Container | — | Stateless — horizontal |
| **Redis** | Managed service | 6379 | Cluster mode |
| **Pubsub/Kafka** | Managed service | — | Partition-based |
| **IDM / Auth Provider** | Enterprise service | — | Existing infrastructure |

### 10.2 MCP Server Transport Modes

| Transport | Used by | Detail |
|---|---|---|
| **stdio** | Sub-agent ↔ backend MCP servers | Agent spawns MCP server as subprocess; communicates over stdin/stdout |
| **Streamable HTTP** | IDE ↔ Bridge | MCP over HTTP POST (JSON-RPC); Bridge exposes `/mcp` endpoint |
| **HTTP** | Agent ↔ Agent (A2A) | A2A JSON-RPC over HTTP POST; Agent Cards at `/.well-known/agent-card.json` |

---

## 11. Technology Stack

### 11.1 Platform Layer

| Component | Technology |
|---|---|
| LLM (Supervisor) | Azure OpenAI (via LiteLlm) |
| Agent Framework (Supervisor) | Google ADK |
| MCP Bridge | FastMCP (Python) |
| A2A Protocol | a2a-sdk (Python) |
| Context Lake | Vector DB (semantic search) |
| Registry | Custom service |
| Cache | Redis |
| Events | Pubsub / Kafka |
| Auth | Enterprise IDM, OAuth2 3LO + PKCE |

### 11.2 Sub-agent Layer (FinOps Example)

| Component | Technology |
|---|---|
| LLM | Vertex AI Gemini 2.5 Pro |
| MCP Framework | mcp[cli] (Python, FastMCP) |
| Data Sources | Google Cloud BigQuery, SQL Server (pymssql) |
| Analytics | NumPy, SciPy |
| Web API | FastAPI + SSE |
| Frontend | React 18, Vite, Recharts |
| Tracing | Pydantic models (TokenUsage, TurnTrace, SessionTrace) |
| Testing | pytest |

### 11.3 MCP Apps Layer

| Component | Technology |
|---|---|
| UI Framework | Any (React, Vue, Svelte, vanilla JS) |
| SDK | `@modelcontextprotocol/ext-apps` (App class) |
| Bundler | Vite + vite-plugin-singlefile |
| Server Registration | `registerAppTool()`, `registerAppResource()` |
| Communication | postMessage (JSON-RPC dialect) |

---

## 12. Non-Functional Requirements

### 12.1 Performance

| Metric | Target |
|---|---|
| End-to-end query response | < 10s for simple queries |
| BigQuery execution timeout | 30s per query |
| Max tool rounds per turn | 15 |
| Token cache hit rate | > 60% (with static tool sets) |
| MCP App iframe load time | < 2s |

### 12.2 Scalability

| Dimension | Approach |
|---|---|
| Department agents | Registry-based dynamic discovery; no Supervisor reconfiguration needed |
| Tools per agent | Tool Search Tool for >50 tools; keyword routing for <50 |
| Concurrent users | Stateless Bridge and Web API scale horizontally |
| Data volume | BigQuery and SQL Server handle cloud-scale data; results truncated at agent layer |

### 12.3 Observability

| Layer | Tooling |
|---|---|
| Agent tracing | Pydantic trace models (per-turn token usage, tool call duration, result sizes) |
| Telemetry | Langfuse (optional) |
| Logging | Python logging (stderr for MCP servers) |
| Metrics | Token counts, cache hit/miss, tool routing accuracy |

### 12.4 Reliability

| Concern | Mitigation |
|---|---|
| LLM failure | Graceful error messages; no partial tool execution |
| MCP server crash | Agent reconnects; stdio servers restarted as subprocesses |
| A2A timeout | 120s HTTP timeout; task state persisted in InMemoryTaskStore |
| Judge loop detection | Supervisor Judge monitors for circular routing and terminates loops |
