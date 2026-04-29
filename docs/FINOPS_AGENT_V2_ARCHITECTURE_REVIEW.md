# FinOps Agent v2 Architecture — Review & Critique

**Scope:** The MCP-native architecture described in `finops-mcp-agent/README.md`, interpreted as a proposed **Version 2** direction (better structure and practices than the original `finops-agent` codebase), compared against `finops-agent/PRD.md` (product and technical expectations for the multi-agent system).

**Date:** 2026-04-29  
**Status:** Architecture review (not an implementation audit)

---

## 1. Executive summary

The proposed v2 architecture is **strong on data boundaries, FinOps-specific safety (elicitation tiers, post-query validation), and a clear progressive roadmap** aligned with course milestones. It is **weaker on enterprise product requirements** that the PRD treats as P0/P1: identity and row-level cost scoping, first-class cancellation and streaming observability to the user, multi-channel deployment, and horizontal scale patterns.

**Verdict:** Use this design as the **core execution and tool plane** (MCP servers + guarded SQL + analytics sidecar), but **do not treat the README alone as a complete v2 product spec**. Extend it explicitly with auth, telemetry, orchestration depth, and operational runbooks before calling it production-grade.

---

## 2. What v2 gets right

### 2.1 Clear separation of concerns

Splitting **BigQuery**, **SQL Server**, **analytics/compute**, **file/reporting**, and **UI push** into separate MCP servers matches real operational boundaries (credentials, dialects, failure domains). This is easier to reason about than a single “god agent” with every tool registered inline.

### 2.2 FinOps-appropriate safety model

Tiered **elicitation** (defaults → warn → ask → block) plus **`validate_results`** addresses the highest-risk failure mode in cost agents: wrong scope, wrong cost column, or misleading aggregates. This is more concrete than many generic agent PRDs.

### 2.3 “Generic tools, intelligent context”

Pushing **schema and guides into MCP Resources** and keeping tools generic (`run_bq_query`) is the right tradeoff for maintainability: fewer bespoke tools, less churn when tables evolve (especially with dynamic SQL Server schema discovery).

### 2.4 Honest about LLM limits

Delegating **statistics, forecasting, and deterministic ranking** to the analytics server avoids the common anti-pattern of asking the model to do numeric inference on large JSON in context.

### 2.5 Progressive delivery without a rewrite

The **session-by-session growth plan** (planning loop → cognitive pipeline → memory MCP → multi-agent → channels) is pragmatic and reduces the risk of boiling the ocean.

---

## 3. Gaps vs the PRD (product and NFR)

The PRD assumes a **web-first product** with OIDC, RBAC, streaming UX, kill switch, and later Slack/GChat, plus observability and K8s scale. The README architecture focuses on **MCP + Gemini + Chrome extension**. The table below highlights mismatches to close deliberately, not accidentally.

| PRD theme | PRD expectation (summary) | v2 README today |
|-----------|---------------------------|-----------------|
| **AuthN / AuthZ** | OIDC (Azure AD), RBAC, query scope to team/project, audit all queries | Not specified; elicitation mentions scope but not enforcement |
| **Streaming / transparency** | SSE events: thinking, handoffs, tool calls, durations, errors | UI server pushes dashboard components; agent-side streaming contract not specified |
| **Kill switch / cancel** | Stop within ~2s, cancel BQ jobs, abort LLM, partial results | Not in architecture diagram or primitives |
| **Multi-agent** | Supervisor, sub-agents, A2A, skills manifest | Single Gemini agent; skills replaced by Resources/Prompts (good, but not equivalent to PRD orchestration) |
| **HITL / A2UI** | Forms, approvals, deferred actions | Tier 2/3 elicitation is conversational; no A2UI/form protocol described |
| **Multi-channel** | Web, Slack, GChat, later API | Chrome extension + stdio MCP; channel abstraction absent |
| **Observability** | OpenTelemetry, structured logs, Prometheus | Not specified |
| **Performance / scale** | Concurrent users, caching, query cost caps | 30s timeout mentioned for BQ; caching and multi-tenant load model absent |
| **Export formats** | PDF, CSV, Excel, scheduled reports | CSV export + markdown-style reports; Excel/PDF/scheduling not specified |

**Critique:** If v2 is marketed as replacing the PRD-backed system, stakeholders will expect **auth, audit, and cancel** on day one. If v2 is positioned as **Session 4–6 course deliverable**, the gap is acceptable provided the doc states **non-goals** for each phase.

---

## 4. Technical and architectural critiques

### 4.1 MCP stdio fan-out and operations

The diagram shows **one agent process** talking to **five stdio MCP servers**. That implies **six long-lived processes per interactive session** (or equivalent multiplexing). For local development this is fine; for **100 concurrent users** (PRD NFR), you need a stated pattern: **per-session supervisor**, **shared remote MCP over HTTP**, or **in-process tools** for hot paths. Without that, “better practices” stop at component boundaries and do not reach deployment reality.

### 4.2 LLM-generated SQL and “guarded” execution

The design relies on **read-only SELECT/WITH** guards. That is necessary but **not sufficient** for compliance narratives: you still need **dry-run/bytes billed estimates**, **max bytes billed**, **statement timeouts**, **partition filters for large tables**, and optionally **allowlisted datasets/views** for less-trusted callers. The PRD’s **parameterized SQL** story is stronger for injection and repeatability than pure natural-language SQL; v2 should document **how** guardrails are implemented (parser, allowlist, resource limits).

### 4.3 Elicitation spec vs example flow inconsistency

The README **Tier 0** table says **“Last month” → previous calendar month**, while the **example flow** uses **“last 30 days”** when no period is specified. That is a small documentation inconsistency but a **large FinOps semantics issue** (calendar month vs rolling window). **Recommendation:** define a single default per intent (“trend” vs “month close”) and encode it in `elicitation://rules` so agent and humans stay aligned.

### 4.4 File server risk surface

Sandboxed `reports/` is good. **Critique:** `edit_file(path, old_text, new_text)` is easy to get wrong (race conditions, ambiguous matches). Prefer **atomic write** (write temp + rename) or **versioned artifacts** for anything that might be re-read by the agent in a loop.

### 4.5 UI coupling

Pushing components to a **Vantage Chrome extension** via SSE is a clear demo integration. For **PRD-grade** UX you will want a **neutral client contract** (same payloads usable from React web app), not only extension-specific assumptions.

### 4.6 Model and stack drift from PRD

PRD targets **Strands / AgentCore / Bedrock / Claude**; README targets **Gemini + FastMCP**. Neither is wrong, but **portability** (model routing, Session 15 in the README) should be a **first-class config axis** so v2 does not become a second vendor-locked codebase next to v1.

---

## 5. Code quality and engineering practices (what v2 should add on paper)

The README describes **folders and filenames** (`finops_agent.py`, `models.py`) but not **engineering standards**. For “v2 = better quality,” explicitly add:

1. **Layering inside `agent/`** — transport (CLI/API), orchestration (plan/react), tool/MCP adapter, prompts/resources loader, and domain types (separate from `models.py` grab-bag).
2. **Contracts** — JSON schemas for analytics tool payloads and UI `push_component`; validate at boundaries.
3. **Testing** — golden tests for SQL guardrails, snapshot tests for elicitation decisions, integration tests with **recorded MCP** or mocked backends.
4. **Observability hooks** — trace IDs per user turn, log **tool name + latency + row counts**, never log secrets or full PII rows.
5. **Configuration** — separate **dev/stage/prod** config; no silent fallback between cost columns in prod without logging.

---

## 6. Recommendations (prioritized)

| Priority | Recommendation |
|----------|------------------|
| **P0** | Add a short **“Non-goals by session”** section to the README (or PRD appendix) so v2 scope is explicit vs enterprise PRD. |
| **P0** | Resolve **default time window** semantics (calendar month vs trailing N days) across elicitation tables and examples. |
| **P0** | Document **cancellation**: cooperative flag in agent loop, BQ job cancel, and UI “Stop” behavior when web UI exists. |
| **P1** | Specify **authz**: how team/project scope flows from host app into prompts and SQL (views, mandatory filters, or post-filter). |
| **P1** | Decide **MCP deployment topology** for multi-user (stdio vs remote MCP) before Phase 2 scale claims. |
| **P1** | Align **streaming event schema** with PRD transparency requirements (tool start/end, errors). |
| **P2** | Plan **HITL** as MCP elicitation / host UI callback, not only natural-language “ask before.” |
| **P2** | Unify **export** story with PRD (CSV first, then Excel/PDF via a dedicated tool or external job). |

---

## 7. Conclusion

The Copilot-aligned **MCP-first v2 architecture** is a **credible and often superior foundation** for maintainable FinOps tooling than an ad-hoc multi-agent v1, especially for **data plane separation, validation, and teaching-oriented progression**. It is **not yet a complete answer** to the PRD’s **platform** requirements (security, lifecycle, multi-channel, orchestration transparency, and scale).

**Suggested framing:** **v2 = MCP cost intelligence core + explicit roadmap to PRD NFRs**, rather than v2 = full replacement for the PRD system until the gaps above are designed and staffed.

---

## References (in-repo)

- `Finops_Project/finops-mcp-agent/README.md` — proposed v2 architecture, primitives, session plan  
- `Finops_Project/finops-agent/PRD.md` — product requirements, NFRs, and v1 technology assumptions  
