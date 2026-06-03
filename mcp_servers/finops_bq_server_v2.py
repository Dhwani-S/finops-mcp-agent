"""
FinOps BigQuery MCP Server — Multi-cloud cost data access layer.

Single MCP server for ALL cloud cost data and recommendations in BigQuery.
One server = one data source (BigQuery), following MCP best practices.

Data Sources (all in cie-costmanagement-prod-152136):
  ┌─────────┬───────────────────────────────────────────┬───────────────┐
  │ Cloud   │ Table                                     │ Type          │
  ├─────────┼───────────────────────────────────────────┼───────────────┤
  │ AWS     │ aws.aws_daily_usage_extended_costs         │ Daily costs   │
  │ AWS     │ aws.aws_recommendations_new                │ Recs          │
  │ Azure   │ azure.daily_usage_costs                    │ Daily costs   │
  │ Azure   │ azure.act_master_azure_portal_recommendation│ Recs         │
  │ GCP     │ gcp.daily_usage_costs                      │ Daily costs   │
  │ GCP     │ gcp.gcp_recommendation                     │ Recs          │
  └─────────┴───────────────────────────────────────────┴───────────────┘

Tools:
  1. get_table_schema      — Discover columns/types at runtime
  2. list_dimension_values  — Look up distinct values before querying
  3. dry_run_query          — Estimate cost without executing
  4. run_query              — Execute read-only SQL
  5. run_multi_cloud_query  — Query across clouds in one call

Run:
    mcp dev mcp_servers/finops_bq_server_v2.py       # Inspector
    python mcp_servers/finops_bq_server_v2.py        # Stdio mode
"""

from __future__ import annotations

import base64
import decimal
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

# ── Configuration ────────────────────────────────────────────────────────

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

BQ_PROJECT = os.getenv("BQ_DATA_PROJECT", "cie-costmanagement-prod-152136")
RESOURCES_DIR = _project_root / "resources"

MAX_RESULT_ROWS = 500
MAX_BYTES_BILLED = 500 * 1024**3  # 500 GB hard cap
QUERY_TIMEOUT_SECONDS = 30
COST_PER_TB = 6.25  # BQ on-demand pricing $/TB

# DML/DDL blocklist — must never appear outside string literals
_BLOCKED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE"
    r"|GRANT|REVOKE|CALL|EXEC)\b",
    re.IGNORECASE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s | %(levelname)s | %(message)s",
    stream=sys.stderr,  # MCP uses stdout for JSON-RPC — logs go to stderr
)
logger = logging.getLogger("finops-bq")

# ── Table Registry ───────────────────────────────────────────────────────
# Canonical list of allowed tables — prevents querying arbitrary datasets.

TABLES = {
    # ── AWS ──
    "aws_costs": {
        "fqn": f"{BQ_PROJECT}.aws.aws_daily_usage_extended_costs",
        "cloud": "AWS",
        "type": "daily_costs",
        "description": "AWS daily usage and extended cost data with business mappings",
        "date_column": "line_item_usage_start_date",
        "cost_columns": ["line_item_unblended_cost", "total_cost", "pricing_public_on_demand_cost"],
    },
    "aws_recommendations": {
        "fqn": f"{BQ_PROJECT}.aws.aws_recommendations_new",
        "cloud": "AWS",
        "type": "recommendations",
        "description": "AWS cost optimization recommendations",
    },
    # ── Azure ──
    "azure_costs": {
        "fqn": f"{BQ_PROJECT}.azure.daily_usage_costs",
        "cloud": "Azure",
        "type": "daily_costs",
        "description": "Azure daily usage cost data",
    },
    "azure_recommendations": {
        "fqn": f"{BQ_PROJECT}.azure.act_master_azure_portal_recommendation",
        "cloud": "Azure",
        "type": "recommendations",
        "description": "Azure portal cost optimization recommendations",
    },
    "azure_utilization": {
        "fqn": f"{BQ_PROJECT}.azure.azure_utilization_metrics",
        "cloud": "Azure",
        "type": "utilization",
        "description": "Azure resource utilization metrics (CPU %, Memory %, etc.) for VM rightsizing analysis. Columns: resource_name, metric_name, metric_value, date, azure_service",
        "date_column": "date",
    },
    # ── GCP ──
    "gcp_costs": {
        "fqn": f"{BQ_PROJECT}.gcp.daily_usage_costs",
        "cloud": "GCP",
        "type": "daily_costs",
        "description": "GCP daily usage cost data with business mappings",
    },
    "gcp_recommendations": {
        "fqn": f"{BQ_PROJECT}.gcp.gcp_recommendation",
        "cloud": "GCP",
        "type": "recommendations",
        "description": "GCP cost optimization recommendations",
    },
    # ── Kubernetes ──
    "gcp_k8s": {
        "fqn": f"{BQ_PROJECT}.gcp.gcp_k8_cost_tracking",
        "cloud": "GCP",
        "type": "k8s_costs",
        "description": "GCP Kubernetes cost tracking — namespace-level CPU core hours, usage vs requested, with ownership mappings",
        "date_column": "dateTime",
        "cost_columns": ["core_hours_cost", "usage_core_cost", "max_req_usg_cost"],
    },
    "azure_k8s": {
        "fqn": f"{BQ_PROJECT}.azure.k8_cost_tracking_integrated",
        "cloud": "Azure",
        "type": "k8s_costs",
        "description": "Azure Kubernetes cost tracking — namespace-level CPU core hours, usage vs requested, wasted cost, with ownership mappings",
        "date_column": "dateTime",
        "cost_columns": ["core_hours_cost", "usage_core_cost", "wasted_cost", "storage_cost"],
    },
    "aws_k8s": {
        "fqn": f"{BQ_PROJECT}.aws.aws_k8_cost_tracking_sync",
        "cloud": "AWS",
        "type": "k8s_costs",
        "description": "AWS Kubernetes cost tracking — namespace-level CPU core hours, usage vs requested, with ownership mappings",
        "date_column": "dateTime",
        "cost_columns": ["core_hours_cost", "usage_core_cost"],
    },
}

# Set of fully-qualified table names for quick validation
_ALLOWED_FQN = {t["fqn"] for t in TABLES.values()}

# ── BigQuery Client (lazy init) ─────────────────────────────────────────

mcp = FastMCP("FinOps-BQ-Server")
_bq_client = None


def _get_client():
    """Lazy-init BQ client. Auth priority:
    1. GCP_DEV_CREDENTIALS_BASE64 (base64 service-account JSON)
    2. GOOGLE_APPLICATION_CREDENTIALS (file path)
    3. Application Default Credentials (gcloud auth)
    """
    global _bq_client
    if _bq_client is not None:
        return _bq_client
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        b64 = os.getenv("GCP_DEV_CREDENTIALS_BASE64")
        keyfile = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if b64:
            info = json.loads(base64.b64decode(b64))
            creds = service_account.Credentials.from_service_account_info(info)
            _bq_client = bigquery.Client(credentials=creds, project=BQ_PROJECT)
            logger.info("BQ client ready (service-account, project=%s)", BQ_PROJECT)
        elif keyfile:
            creds = service_account.Credentials.from_service_account_file(keyfile)
            _bq_client = bigquery.Client(credentials=creds, project=BQ_PROJECT)
            logger.info("BQ client ready (keyfile, project=%s)", BQ_PROJECT)
        else:
            _bq_client = bigquery.Client(project=BQ_PROJECT)
            logger.info("BQ client ready (ADC, project=%s)", BQ_PROJECT)
    except Exception as exc:
        logger.error("BQ client init failed: %s", exc, exc_info=True)
        _bq_client = None
    return _bq_client


# ── SQL Validation ───────────────────────────────────────────────────────

def _validate_sql(sql: str) -> str | None:
    """Return error message if SQL is invalid, else None."""
    clean = sql.strip()

    if not re.match(r"^(SELECT|WITH)\s", clean, re.IGNORECASE):
        return "Only SELECT / WITH statements are permitted."

    # Strip string literals before keyword scan
    no_strings = re.sub(r"'[^']*'", "''", clean)
    hit = _BLOCKED_SQL.search(no_strings)
    if hit:
        return f"Blocked keyword: {hit.group(0).upper()}"

    # No multi-statement
    if ";" in clean.rstrip(";").strip():
        return "Multi-statement queries are not allowed."

    # Must reference our data project
    if BQ_PROJECT not in clean:
        return f"Use fully-qualified table names including project: {BQ_PROJECT}"

    return None


# Scope filter columns — if any appear in WHERE or GROUP BY, query is scoped
_SCOPE_COLS = re.compile(
    r"\b(project_name|cpe_project_name|gcp_project_name|project_id"
    r"|line_item_usage_account_id|account_name|bill_payer_account_id"
    r"|subscription_name|subscription_id|resource_group"
    r"|business_unit|sleeve|dept_code"
    r"|exec_owner|executive_owner|product_owner|finance_owner|agm_bgm"
    r"|environment|owner|team|core_id)\b",
    re.IGNORECASE,
)

_COST_AGG = re.compile(
    r"\b(SUM|AVG|TOTAL)\s*\("
    r"|\b(total_cost|line_item_unblended_cost|cost_with_credits|cost"
    r"|pricing_public_on_demand_cost|cluster_cost|support_cost|admin_cost)\b",
    re.IGNORECASE,
)


def _check_scope(sql: str) -> str | None:
    """Reject unscoped org-wide cost aggregations. Returns error or None."""
    if not _COST_AGG.search(sql):
        return None

    where = re.search(r"\bWHERE\b(.+)", sql, re.IGNORECASE | re.DOTALL)
    if where and _SCOPE_COLS.search(where.group(1)):
        return None

    group = re.search(
        r"\bGROUP\s+BY\b(.+?)(?:ORDER|LIMIT|HAVING|$)",
        sql, re.IGNORECASE | re.DOTALL,
    )
    if group and _SCOPE_COLS.search(group.group(1)):
        return None

    return (
        "SCOPE REQUIRED — This query aggregates cost data across the entire "
        "organization without a project/team/owner filter. Ask the user:\n"
        "1. Organization-wide (confirm explicitly)\n"
        "2. Specific project (filter by project_name, account_name, etc.)\n"
        "3. Specific owner/team (use list_dimension_values to find values)\n\n"
        "If user confirms org-wide, re-call with org_wide_confirmed=true."
    )


# ── Helpers ──────────────────────────────────────────────────────────────

_VALID_COL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _serialize(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _load_resource(rel_path: str) -> str:
    p = (RESOURCES_DIR / rel_path).resolve()
    if not p.exists():
        return f"Error: resource not found — {rel_path}"
    return p.read_text(encoding="utf-8")


# ── Tool 1: get_table_schema ────────────────────────────────────────────

@mcp.tool()
def get_table_schema(
    table: str = Field(
        description=(
            "Fully-qualified BQ table name "
            "(e.g. cie-costmanagement-prod-152136.aws.aws_daily_usage_extended_costs) "
            "OR a short alias: aws_costs, aws_recommendations, azure_costs, "
            "azure_recommendations, gcp_costs, gcp_recommendations"
        ),
    ),
) -> str:
    """Discover the schema (columns, types, descriptions) of a BigQuery table.

    Call this BEFORE writing queries to get exact column names and types.
    Accepts either a fully-qualified table name or a short alias.

    Available tables:
    - aws_costs             → AWS daily usage & extended costs
    - aws_recommendations   → AWS optimization recommendations
    - azure_costs           → Azure daily usage costs
    - azure_recommendations → Azure portal recommendations
    - gcp_costs             → GCP daily usage costs
    - gcp_recommendations   → GCP optimization recommendations
    """
    client = _get_client()
    if not client:
        return "Error: BQ client not initialized — check credentials."

    # Resolve alias → FQN
    fqn = table.strip().strip("`")
    if fqn in TABLES:
        fqn = TABLES[fqn]["fqn"]

    if fqn not in _ALLOWED_FQN:
        return (
            f"Error: Unknown table. Available: "
            + ", ".join(sorted(TABLES.keys()))
        )

    try:
        ref = client.get_table(fqn)
        cols = []
        for f in ref.schema:
            c = {"name": f.name, "type": f.field_type, "mode": f.mode}
            if f.description:
                c["description"] = f.description
            cols.append(c)

        return json.dumps({
            "table": fqn,
            "column_count": len(cols),
            "total_rows": ref.num_rows,
            "size_gb": round((ref.num_bytes or 0) / 1024**3, 2),
            "columns": cols,
        }, default=str)
    except Exception as exc:
        logger.exception("Schema lookup failed")
        return f"Error: Schema lookup failed — {exc}"


# ── Tool 2: list_dimension_values ────────────────────────────────────────

@mcp.tool()
def list_dimension_values(
    table: str = Field(
        description=(
            "Fully-qualified BQ table or short alias "
            "(aws_costs, azure_costs, gcp_costs, aws_recommendations, "
            "azure_recommendations, gcp_recommendations)"
        ),
    ),
    column: str = Field(
        description="Column name to get distinct values for (e.g. product_servicename, service_description)"
    ),
    filter_term: str = Field(
        default="",
        description="Optional text filter — returns only values containing this term (case-insensitive)",
    ),
    limit: int = Field(default=25, ge=1, le=100, description="Max distinct values to return"),
) -> str:
    """Look up distinct values for a column, sorted by frequency.

    Use BEFORE writing queries to find exact entity names (services, projects,
    accounts, regions, owners). Never guess column values — look them up first.

    WHEN TO USE:
    - User mentions a project, service, account, region, or owner by name
    - You need to verify what values exist before filtering in run_query
    - User's term is vague and might match multiple entries
    """
    client = _get_client()
    if not client:
        return "Error: BQ client not initialized — check credentials."

    fqn = table.strip().strip("`")
    if fqn in TABLES:
        fqn = TABLES[fqn]["fqn"]
    if fqn not in _ALLOWED_FQN:
        return f"Error: Unknown table. Available: {', '.join(sorted(TABLES.keys()))}"

    if not _VALID_COL.match(column):
        return "Error: Invalid column name — use only letters, numbers, underscores."

    limit = max(1, min(limit, 100))

    try:
        from google.cloud import bigquery as bq

        if filter_term:
            sql = (
                f"SELECT `{column}` AS value, COUNT(*) AS row_count "
                f"FROM `{fqn}` "
                f"WHERE LOWER(CAST(`{column}` AS STRING)) LIKE LOWER(@filter) "
                f"GROUP BY `{column}` ORDER BY row_count DESC LIMIT @lim"
            )
            params = [
                bq.ScalarQueryParameter("filter", "STRING", f"%{filter_term}%"),
                bq.ScalarQueryParameter("lim", "INT64", limit),
            ]
        else:
            sql = (
                f"SELECT `{column}` AS value, COUNT(*) AS row_count "
                f"FROM `{fqn}` "
                f"GROUP BY `{column}` ORDER BY row_count DESC LIMIT @lim"
            )
            params = [bq.ScalarQueryParameter("lim", "INT64", limit)]

        cfg = bq.QueryJobConfig(
            maximum_bytes_billed=MAX_BYTES_BILLED,
            query_parameters=params,
        )
        rows = list(client.query(sql, job_config=cfg).result(timeout=QUERY_TIMEOUT_SECONDS))

        if not rows:
            msg = f"No values found for '{column}' in {fqn}"
            if filter_term:
                msg += f" matching '{filter_term}'"
            return msg

        return json.dumps({
            "table": fqn,
            "column": column,
            "filter": filter_term or "(none)",
            "count": len(rows),
            "values": [{"value": r["value"], "row_count": r["row_count"]} for r in rows],
        }, default=str)
    except Exception as exc:
        logger.exception("Dimension lookup failed")
        return f"Error: Dimension lookup failed — {exc}"


# ── Tool 3: dry_run_query ────────────────────────────────────────────────

@mcp.tool()
def dry_run_query(
    sql: str = Field(description="BigQuery Standard SQL query to validate and estimate cost"),
) -> str:
    """Validate a query and estimate bytes scanned WITHOUT executing it.

    Use BEFORE run_query when the query might be expensive (org-wide, large
    date ranges, no LIMIT). Catches syntax errors cheaply.

    Returns estimated bytes, GB, and cost at $6.25/TB.
    """
    client = _get_client()
    if not client:
        return "Error: BQ client not initialized."

    err = _validate_sql(sql)
    if err:
        return f"Error: {err}"

    try:
        from google.cloud import bigquery as bq

        job = client.query(
            sql.strip().rstrip(";"),
            job_config=bq.QueryJobConfig(dry_run=True, use_query_cache=False),
        )
        b = job.total_bytes_processed or 0
        gb = b / 1024**3
        cost = (b / 1024**4) * COST_PER_TB

        status = "ok"
        if b > MAX_BYTES_BILLED:
            status = "blocked"
        elif gb > 100:
            status = "expensive"
        elif gb > 10:
            status = "moderate"

        return json.dumps({
            "status": status,
            "bytes_estimated": b,
            "gb_estimated": round(gb, 2),
            "cost_estimated_usd": round(cost, 4),
            "message": (
                f"~{round(gb, 1)} GB (~${round(cost, 3)}). "
                + ("BLOCKED — exceeds 500 GB cap." if status == "blocked" else "Safe to execute.")
            ),
        })
    except Exception as exc:
        err_str = str(exc)
        if "Syntax error" in err_str or "Unrecognized name" in err_str:
            return json.dumps({"status": "syntax_error", "error": err_str})
        logger.exception("Dry run failed")
        return f"Error: Dry run failed — {exc}"


# ── Tool 4: run_query ────────────────────────────────────────────────────

@mcp.tool()
def run_query(
    sql: str = Field(description="BigQuery Standard SQL (SELECT/WITH only). Must use fully-qualified table names."),
    org_wide_confirmed: bool = Field(
        default=False,
        description="Set true ONLY after user explicitly confirms organization-wide scope",
    ),
) -> str:
    """Execute a read-only BigQuery query against FinOps cost data.

    Returns JSON array (max 500 rows). Only SELECT/WITH allowed.
    Must use fully-qualified table names with project cie-costmanagement-prod-152136.

    PREREQUISITES:
    1. Call get_table_schema to learn column names/types
    2. Call list_dimension_values to verify entity names before WHERE filters
    3. Call dry_run_query to estimate cost for expensive queries

    AVAILABLE TABLES:
    - `cie-costmanagement-prod-152136.aws.aws_daily_usage_extended_costs`
        AWS daily costs. Key cols: line_item_usage_start_date, line_item_product_code,
        product_servicename, line_item_unblended_cost, total_cost, account_name,
        project_name, environment, business_unit, executive_owner
    - `cie-costmanagement-prod-152136.aws.aws_recommendations_new`
        AWS optimization recommendations
    - `cie-costmanagement-prod-152136.azure.daily_usage_costs`
        Azure daily costs
    - `cie-costmanagement-prod-152136.azure.act_master_azure_portal_recommendation`
        Azure portal recommendations
    - `cie-costmanagement-prod-152136.gcp.daily_usage_costs`
        GCP daily costs. Key cols: dateTime, service_description, cost_with_credits,
        cpe_project_name, environment, exec_owner
    - `cie-costmanagement-prod-152136.gcp.gcp_recommendation`
        GCP optimization recommendations

    SYNTAX REMINDERS (BigQuery Standard SQL):
    - Use LIMIT N (not TOP N)
    - Azure dateTime may be TIMESTAMP — use DATE(dateTime) for date comparisons
    - GCP/AWS date columns are DATE — compare directly
    - Use DATE_TRUNC, DATE_SUB, CURRENT_DATE() for date math
    - Use SAFE_DIVIDE for division to avoid /0 errors
    """
    client = _get_client()
    if not client:
        return "Error: BQ client not initialized."

    err = _validate_sql(sql)
    if err:
        return f"Error: {err}"

    if not org_wide_confirmed:
        scope_err = _check_scope(sql)
        if scope_err:
            return f"Error: {scope_err}"

    try:
        from google.cloud import bigquery as bq

        t0 = time.time()
        job = client.query(
            sql.strip().rstrip(";"),
            job_config=bq.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
        )
        rows = [_serialize(dict(r)) for r in job.result(timeout=QUERY_TIMEOUT_SECONDS)]
        elapsed = time.time() - t0
        logger.info("Query returned %d rows in %.1fs", len(rows), elapsed)

        if not rows:
            return "Query executed successfully but returned 0 rows."

        truncated = len(rows) > MAX_RESULT_ROWS
        out = json.dumps(rows[:MAX_RESULT_ROWS], indent=None)
        if truncated:
            out += f"\n[Truncated: {MAX_RESULT_ROWS} of {len(rows)} rows]"
        return out
    except Exception as exc:
        logger.exception("Query execution failed")
        return f"Error: Query failed — {exc}"


# ── Tool 5: run_multi_cloud_query ────────────────────────────────────────

@mcp.tool()
def run_multi_cloud_query(
    aws_sql: str = Field(default="", description="SQL for AWS data. Leave empty to skip."),
    azure_sql: str = Field(default="", description="SQL for Azure data. Leave empty to skip."),
    gcp_sql: str = Field(default="", description="SQL for GCP data. Leave empty to skip."),
    top_n: int = Field(default=10, ge=1, le=100, description="Top rows in unified result"),
    sort_by: str = Field(default="cost", description="Column to sort by descending"),
    org_wide_confirmed: bool = Field(
        default=False,
        description="Set true ONLY after user explicitly confirms organization-wide scope",
    ),
) -> str:
    """Query across multiple clouds in ONE call and return a unified result.

    Use this INSTEAD of calling run_query 3 times — avoids flooding context.
    Each SQL is optional. Results are combined with a _cloud label and sorted.

    Use consistent column aliases across queries (e.g. always alias cost as "cost").
    """
    client = _get_client()
    if not client:
        return "Error: BQ client not initialized."

    queries = {
        "AWS": aws_sql.strip() if aws_sql else "",
        "Azure": azure_sql.strip() if azure_sql else "",
        "GCP": gcp_sql.strip() if gcp_sql else "",
    }
    active = {c: s for c, s in queries.items() if s}
    if not active:
        return "Error: Provide at least one SQL query."

    for cloud, s in active.items():
        err = _validate_sql(s)
        if err:
            return f"Error in {cloud}: {err}"

    # Scope guard — same as run_query
    if not org_wide_confirmed:
        for cloud, s in active.items():
            scope_err = _check_scope(s)
            if scope_err:
                return f"Error: {scope_err}"

    from google.cloud import bigquery as bq

    combined = []
    summary = {}
    errors = []

    for cloud, s in active.items():
        try:
            t0 = time.time()
            job = client.query(
                s.rstrip(";"),
                job_config=bq.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
            )
            rows = [_serialize(dict(r)) for r in job.result(timeout=QUERY_TIMEOUT_SECONDS)]
            elapsed = time.time() - t0
            logger.info("%s: %d rows in %.1fs", cloud, len(rows), elapsed)

            for r in rows[:MAX_RESULT_ROWS]:
                r["_cloud"] = cloud
                combined.append(r)

            costs = []
            for r in rows:
                for k, v in r.items():
                    if any(w in k.lower() for w in ("cost", "spend", "total")) and isinstance(v, (int, float)):
                        costs.append(v)
                        break

            summary[cloud] = {
                "rows": len(rows),
                "total": round(sum(costs), 2) if costs else 0,
                "time_s": round(elapsed, 1),
            }
        except Exception as exc:
            logger.exception("%s query failed", cloud)
            errors.append({"cloud": cloud, "error": str(exc)})
            summary[cloud] = {"rows": 0, "total": 0, "error": str(exc)}

    if not combined and errors:
        return f"Error: All queries failed — {json.dumps(errors)}"

    top_n = max(1, min(top_n, 100))
    try:
        combined.sort(
            key=lambda r: float(r.get(sort_by, 0)) if isinstance(r.get(sort_by), (int, float)) else 0,
            reverse=True,
        )
    except (ValueError, TypeError):
        pass

    result = {
        "clouds_queried": list(active.keys()),
        "grand_total": round(sum(s.get("total", 0) for s in summary.values()), 2),
        "per_cloud": summary,
        "top_results": combined[:top_n],
        "total_rows": len(combined),
    }
    if errors:
        result["errors"] = errors

    return json.dumps(result, default=str)


# ── MCP Resources: Table Registry ───────────────────────────────────────

@mcp.resource("finops://tables")
def resource_table_registry() -> str:
    """Complete registry of all available FinOps BigQuery tables with metadata."""
    return json.dumps(TABLES, indent=2)


# ── MCP Resources: Schemas (static files) ───────────────────────────────

@mcp.resource("schema://aws/daily_costs")
def schema_aws_costs() -> str:
    """AWS daily cost table schema — columns, types, descriptions."""
    return _load_resource("schemas/bq_aws_daily_costs.json")


@mcp.resource("schema://aws/recommendations")
def schema_aws_recommendations() -> str:
    """AWS recommendations table schema."""
    return _load_resource("schemas/bq_aws_recommendations.json")


@mcp.resource("schema://azure/daily_costs")
def schema_azure_costs() -> str:
    """Azure daily cost table schema."""
    return _load_resource("schemas/bq_azure_daily_costs.json")


@mcp.resource("schema://azure/recommendations")
def schema_azure_recommendations() -> str:
    """Azure portal recommendations table schema."""
    return _load_resource("schemas/bq_azure_recommendations.json")


@mcp.resource("schema://gcp/daily_costs")
def schema_gcp_costs() -> str:
    """GCP daily cost table schema."""
    return _load_resource("schemas/bq_gcp_daily_costs.json")


@mcp.resource("schema://gcp/recommendations")
def schema_gcp_recommendations() -> str:
    """GCP recommendation table schema."""
    return _load_resource("schemas/bq_gcp_recommendations.json")


@mcp.resource("schema://gcp/k8s")
def schema_gcp_k8s() -> str:
    """GCP Kubernetes cost tracking table schema."""
    return _load_resource("schemas/bq_gcp_k8s.json")


@mcp.resource("schema://azure/k8s")
def schema_azure_k8s() -> str:
    """Azure Kubernetes cost tracking table schema."""
    return _load_resource("schemas/bq_azure_k8s.json")


@mcp.resource("schema://aws/k8s")
def schema_aws_k8s() -> str:
    """AWS Kubernetes cost tracking table schema."""
    return _load_resource("schemas/bq_aws_k8s.json")


# ── MCP Prompts ──────────────────────────────────────────────────────────

@mcp.prompt()
def cost_breakdown(
    cloud: str = "all",
    dimension: str = "service",
    period: str = "last 30 days",
) -> str:
    """Analyze cloud costs grouped by a dimension for a time period."""
    return f"""Analyze {cloud} cloud costs grouped by {dimension} for {period}.

Steps:
1. Call get_table_schema for the relevant cost table(s) to get column names.
2. Write a query grouping by the appropriate dimension column.
3. Call dry_run_query to estimate cost.
4. Execute with run_query (or run_multi_cloud_query if cloud="all").
5. Present:
   - Top 10 items by spend (table)
   - Total spend
   - Daily trend if period > 7 days
6. Flag partial periods or data gaps.

Cost columns: AWS=total_cost, GCP=cost_with_credits, Azure=check schema."""


@mcp.prompt()
def compare_periods(
    cloud: str = "all",
    metric: str = "total spend",
    period_a: str = "last month",
    period_b: str = "this month",
) -> str:
    """Compare a cost metric between two time periods."""
    return f"""Compare {metric} between '{period_a}' and '{period_b}' for {cloud}.

Steps:
1. Get schema for column names.
2. Write a single CTE query computing both periods.
3. Show total + top 5 per period with percent change (SAFE_DIVIDE).
4. Highlight significant variances (>20% change)."""


@mcp.prompt()
def investigate_anomaly(
    service: str = "",
    date: str = "",
    cloud: str = "all",
) -> str:
    """Investigate a cost anomaly for a service and date."""
    svc = f"for '{service}'" if service else "across all services"
    dt = f"on {date}" if date else "over the last 7 days"
    return f"""Investigate the cost anomaly {svc} {dt} in {cloud}.

Steps:
1. Query daily spend for 30-day window around the anomaly.
2. Calculate baseline (mean, std) from surrounding days.
3. Report anomaly spend vs baseline ($, %, z-score).
4. Break down by sub-dimensions (resource, SKU, region).
5. Recommend next steps."""


# ── Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
