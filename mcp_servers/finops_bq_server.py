"""
FinOps BigQuery Server — MCP server for multi-cloud cost data access.

Serves cost data, utilization metrics, and GCP recommendations from BigQuery.
All queries are read-only with SQL guardrails, bytes-billed caps, and row limits.

Run:
    # Dev inspector (test tools/resources/prompts in browser)
    mcp dev mcp_servers/finops_bq_server.py

    # Stdio mode (how the agent connects)
    python mcp_servers/finops_bq_server.py
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
if not PROJECT_ID:
    logger.warning("GCP_PROJECT_ID not set — BQ queries will fail")
RESOURCES_DIR = _project_root / "resources"

MAX_RESULT_ROWS = 500
MAX_BYTES_BILLED = 500 * 1024 * 1024 * 1024  # 500 GB
QUERY_TIMEOUT_SECONDS = 30

# DML/DDL keywords that must never appear in a query
_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE|CALL|EXEC)\b",
    re.IGNORECASE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # MCP uses stdout for protocol — logs must go to stderr
)
logger = logging.getLogger("finops_bq_server")

# ---------------------------------------------------------------------------
# BigQuery client (lazy — fails gracefully if credentials missing)
# ---------------------------------------------------------------------------

mcp = FastMCP("FinOps-BigQuery-Server")

bq_client = None

def _init_bq_client():
    """Initialize BQ client on first use. Returns client or None.
    
    Auth priority:
    1. GCP_DEV_CREDENTIALS_BASE64 env var (base64-encoded service account JSON)
    2. GOOGLE_APPLICATION_CREDENTIALS env var (file path to key JSON)
    3. Application Default Credentials (gcloud auth application-default login)
    """
    global bq_client
    if bq_client is not None:
        return bq_client
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        b64_creds = os.getenv("GCP_DEV_CREDENTIALS_BASE64")
        creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if b64_creds:
            creds_json = json.loads(base64.b64decode(b64_creds))
            credentials = service_account.Credentials.from_service_account_info(creds_json)
            bq_client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
            logger.info("BQ client initialized from base64 credentials for project: %s", PROJECT_ID)
        elif creds_file:
            credentials = service_account.Credentials.from_service_account_file(creds_file)
            bq_client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
            logger.info("BQ client initialized from key file for project: %s", PROJECT_ID)
        else:
            bq_client = bigquery.Client(project=PROJECT_ID)
            logger.info("BQ client initialized with ADC for project: %s", PROJECT_ID)
    except Exception as e:
        logger.error("Could not initialize BigQuery client: %s", e, exc_info=True)
        bq_client = None
    return bq_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_resource_file(relative_path: str) -> str:
    """Load a resource file from the resources/ directory."""
    path = (RESOURCES_DIR / relative_path).resolve()
    if not path.exists():
        return f"Error: Resource file not found: {relative_path}"
    return path.read_text(encoding="utf-8")


def _validate_sql(sql: str) -> str | None:
    """Validate a SQL query. Returns error message or None if valid."""
    clean = sql.strip()

    # Must start with SELECT or WITH
    if not re.match(r"^(SELECT|WITH)\s", clean, re.IGNORECASE):
        return "Only SELECT/WITH statements are permitted."

    # Strip string literals before keyword check so values like 'Delete' don't trigger
    no_strings = re.sub(r"'[^']*'", "''", clean)

    # Reject DML/DDL keywords anywhere in query
    match = _BLOCKED_KEYWORDS.search(no_strings)
    if match:
        return f"Blocked keyword detected: {match.group(0).upper()}"

    # Reject multi-statement (semicolons not at the very end)
    stripped = clean.rstrip(";").strip()
    if ";" in stripped:
        return "Multi-statement queries are not allowed."

    # Must reference our project (fully qualified table names)
    if PROJECT_ID not in clean:
        return f"Use fully qualified table names including project: {PROJECT_ID}"

    return None


# Columns that indicate the query is scoped to a specific team/project/owner
_SCOPE_FILTERS = re.compile(
    r"\b(cpe_project_name|gcp_project_name|project_id|project_name"
    r"|linked_account_id|linked_account_name"
    r"|subscription_name|subscription_id|resource_group"
    r"|owner|team|business_unit|environment|core_id)\b",
    re.IGNORECASE,
)

# Patterns that indicate the query aggregates cost data
_COST_AGGREGATION = re.compile(
    r"\b(SUM|AVG|TOTAL)\s*\("
    r"|\b(total_cost|azure_cost|cost_with_credits|cost|total_spend)\b",
    re.IGNORECASE,
)


def _check_scope(sql: str) -> str | None:
    """Reject aggregate cost queries that have no scope filter.

    Returns an error message if the query looks like an unscoped org-wide
    cost aggregation. Returns None if the query is fine.
    """
    clean = sql.strip()

    # Only enforce on queries that aggregate cost columns
    if not _COST_AGGREGATION.search(clean):
        return None  # not a cost aggregation — allow

    # Check if there's a scope filter in the WHERE clause
    where_match = re.search(r"\bWHERE\b(.+)", clean, re.IGNORECASE | re.DOTALL)
    if where_match:
        where_clause = where_match.group(1)
        if _SCOPE_FILTERS.search(where_clause):
            return None  # has a scope filter — allow

    # Check if scope column is in GROUP BY (e.g. "GROUP BY cpe_project_name")
    group_match = re.search(r"\bGROUP\s+BY\b(.+?)(?:ORDER|LIMIT|HAVING|$)", clean, re.IGNORECASE | re.DOTALL)
    if group_match:
        group_clause = group_match.group(1)
        if _SCOPE_FILTERS.search(group_clause):
            return None  # grouped by scope — allow

    return (
        "SCOPE REQUIRED: This query aggregates cost data across the entire organization "
        "without filtering by project, team, or owner. Before running this query, "
        "ask the user which scope they want:\n"
        "1. Organization-wide (confirm explicitly)\n"
        "2. A specific project (use cpe_project_name or gcp_project_name)\n"
        "3. A specific team or owner (use bq_list_dimension_values to find the value)\n\n"
        "If the user confirms organization-wide, re-call run_bq_query with "
        "org_wide_confirmed=true and the same SQL."
    )


def _serialize_row(row: dict) -> dict:
    """Convert BQ row values to JSON-serializable types."""
    out = {}
    for key, value in row.items():
        if isinstance(value, decimal.Decimal):
            out[key] = float(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


# Column name validation pattern — alphanumeric + underscore only
_VALID_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Allowed tables for dimension lookups (fully qualified)
_ALLOWED_TABLES = {
    f"{PROJECT_ID}.gcp.daily_usage_costs",
    f"{PROJECT_ID}.aws.aws_daily_usage_extended_costs",
    f"{PROJECT_ID}.azure.daily_usage_costs",
    f"{PROJECT_ID}.reporting_data.gcp_recommendation",
}


# ---------------------------------------------------------------------------
# Tool: list_dimension_values
# ---------------------------------------------------------------------------

@mcp.tool()
def bq_list_dimension_values(
    table: str,
    column: str,
    filter_term: str = "",
    limit: int = 25,
) -> str:
    """Look up distinct values for a column in a BigQuery cost table.

    DATA SCOPE: GCP costs, AWS costs, Azure costs, utilization metrics, GCP recommendations.
    DO NOT USE for: Azure/AWS recommendations, K8s costs, identity lookups — use sql_list_dimension_values instead.

    Use this BEFORE writing any run_bq_query to find exact entity values that exist in the data.
    Returns distinct values sorted by frequency (most common first).

    WHEN TO USE:
    - User mentions a project, service, account, region, owner, or team by name
    - You need to verify what values exist before filtering in run_bq_query
    - User's term is vague and might match multiple entries

    Args:
        table: Fully qualified BQ table (e.g. cie-costmanagement-803717.gcp.daily_usage_costs).
        column: Column name to look up distinct values for (e.g. cpe_project_name, service_description).
        filter_term: Optional text filter — returns only values containing this term (case-insensitive). Leave empty to list all values.
        limit: Max number of distinct values to return. Default 25.
    """
    client = _init_bq_client()
    if not client:
        return "Error: BigQuery client not initialized. Check credentials."

    # Validate table is in our allowed list
    clean_table = table.strip().strip("`")
    if clean_table not in _ALLOWED_TABLES:
        return (
            f"Error: Table not recognized. Allowed tables: "
            + ", ".join(sorted(_ALLOWED_TABLES))
        )

    # Validate column name — strict alphanumeric to prevent injection
    if not _VALID_COLUMN.match(column):
        return "Error: Invalid column name. Use only letters, numbers, and underscores."

    # Clamp limit
    limit = max(1, min(limit, 100))

    try:
        from google.cloud import bigquery as bq

        # Build parameterized query
        if filter_term:
            sql = (
                f"SELECT `{column}` AS value, COUNT(*) AS row_count "
                f"FROM `{clean_table}` "
                f"WHERE LOWER(CAST(`{column}` AS STRING)) LIKE LOWER(@filter) "
                f"GROUP BY `{column}` "
                f"ORDER BY row_count DESC "
                f"LIMIT @lim"
            )
            job_config = bq.QueryJobConfig(
                maximum_bytes_billed=MAX_BYTES_BILLED,
                query_parameters=[
                    bq.ScalarQueryParameter("filter", "STRING", f"%{filter_term}%"),
                    bq.ScalarQueryParameter("lim", "INT64", limit),
                ],
            )
        else:
            sql = (
                f"SELECT `{column}` AS value, COUNT(*) AS row_count "
                f"FROM `{clean_table}` "
                f"GROUP BY `{column}` "
                f"ORDER BY row_count DESC "
                f"LIMIT @lim"
            )
            job_config = bq.QueryJobConfig(
                maximum_bytes_billed=MAX_BYTES_BILLED,
                query_parameters=[
                    bq.ScalarQueryParameter("lim", "INT64", limit),
                ],
            )

        job = client.query(sql, job_config=job_config)
        results = job.result(timeout=QUERY_TIMEOUT_SECONDS)
        rows = [{"value": row["value"], "row_count": row["row_count"]} for row in results]

        if not rows:
            msg = f"No values found for column '{column}' in {clean_table}"
            if filter_term:
                msg += f" matching '{filter_term}'"
            return msg

        output = {
            "table": clean_table,
            "column": column,
            "filter": filter_term or "(none)",
            "count": len(rows),
            "values": rows,
        }
        return json.dumps(output, indent=None, default=str)

    except Exception as e:
        logger.exception("Dimension lookup failed")
        return f"Error: Dimension lookup failed — {e}"


# ---------------------------------------------------------------------------
# Tool: run_bq_query
# ---------------------------------------------------------------------------

@mcp.tool()
def run_bq_query(sql: str, org_wide_confirmed: bool = False) -> str:
    """Execute a read-only BigQuery SQL query against FinOps cost data.

    DATA SCOPE: GCP costs, AWS costs, Azure costs, utilization metrics, GCP recommendations.
    DO NOT USE for: Azure/AWS recommendations, K8s costs — use run_sql_query instead.

    PREREQUISITE: You MUST call bq_list_dimension_values first to confirm exact entity names
    (project names, service names, etc.) before using them in WHERE clauses. Do NOT guess column values.

    Returns results as JSON (max 500 rows). Only SELECT/WITH statements allowed.
    Must use fully qualified table names with project ID (cie-costmanagement-803717.dataset.table).

    SYNTAX REMINDERS:
    - Use LIMIT N (not TOP N — that's T-SQL)
    - Azure dateTime is TIMESTAMP — use DATE(dateTime) for date comparisons
    - GCP/AWS date columns are DATE type — compare directly

    Args:
        sql: BigQuery Standard SQL query string.
        org_wide_confirmed: Set to true ONLY after the user has explicitly confirmed they want
            organization-wide data (not scoped to a project/team/owner). Default false.
    """
    client = _init_bq_client()
    if not client:
        return "Error: BigQuery client not initialized. Check credentials and GCP_PROJECT_ID."

    # Validate
    error = _validate_sql(sql)
    if error:
        logger.warning("SQL validation failed: %s", error)
        return f"Error: {error}"

    # Scope enforcement — reject unscoped org-wide cost aggregations
    if not org_wide_confirmed:
        scope_error = _check_scope(sql)
        if scope_error:
            logger.warning("Scope check failed for query")
            return f"Error: {scope_error}"

    try:
        from google.cloud import bigquery as bq

        job_config = bq.QueryJobConfig(
            maximum_bytes_billed=MAX_BYTES_BILLED,
        )

        start = time.time()
        job = client.query(sql.strip().rstrip(";"), job_config=job_config)
        results = job.result(timeout=QUERY_TIMEOUT_SECONDS)

        rows = [_serialize_row(dict(row)) for row in results]
        elapsed = time.time() - start
        logger.info("BQ query returned %d rows in %.1fs", len(rows), elapsed)

        if not rows:
            return "Query executed successfully but returned 0 rows."

        truncated = len(rows) > MAX_RESULT_ROWS
        output = json.dumps(rows[:MAX_RESULT_ROWS], indent=None)
        if truncated:
            output += f"\n[Truncated to {MAX_RESULT_ROWS} of {len(rows)} total rows]"
        return output

    except Exception as e:
        logger.exception("BigQuery execution failed")
        return f"Error: Query failed — {e}"


# ---------------------------------------------------------------------------
# Tool: dry_run_bq_query
# ---------------------------------------------------------------------------

@mcp.tool()
def dry_run_bq_query(sql: str) -> str:
    """Validate a BigQuery SQL query and estimate bytes scanned WITHOUT executing it.

    Use this BEFORE run_bq_query when:
    - The query might be expensive (org-wide, large date ranges, no LIMIT)
    - You want to catch syntax errors cheaply
    - You want to preview estimated cost before committing

    Returns estimated bytes to be scanned and approximate cost at $6.25/TB.
    Does NOT execute the query or return any data.

    Args:
        sql: BigQuery Standard SQL query to validate.
    """
    client = _init_bq_client()
    if not client:
        return "Error: BigQuery client not initialized. Check credentials and GCP_PROJECT_ID."

    error = _validate_sql(sql)
    if error:
        return f"Error: {error}"

    try:
        from google.cloud import bigquery as bq

        job_config = bq.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = client.query(sql.strip().rstrip(";"), job_config=job_config)

        bytes_est = job.total_bytes_processed or 0
        gb = bytes_est / (1024 ** 3)
        tb = bytes_est / (1024 ** 4)
        cost_est = tb * 6.25  # On-demand pricing: $6.25/TB

        status = "ok"
        if bytes_est > MAX_BYTES_BILLED:
            status = "blocked"
        elif gb > 100:
            status = "expensive"
        elif gb > 10:
            status = "moderate"

        return json.dumps({
            "status": status,
            "bytes_estimated": bytes_est,
            "gb_estimated": round(gb, 2),
            "cost_estimated_usd": round(cost_est, 4),
            "max_bytes_allowed": MAX_BYTES_BILLED,
            "message": (
                f"Query would scan ~{round(gb, 1)} GB (~${round(cost_est, 3)}). "
                + ("BLOCKED: exceeds 500 GB cap." if status == "blocked" else "Safe to execute.")
            ),
        })

    except Exception as e:
        error_str = str(e)
        # BQ dry run errors usually contain the syntax error details
        if "Syntax error" in error_str or "Unrecognized name" in error_str:
            return json.dumps({
                "status": "syntax_error",
                "error": error_str,
                "message": "Fix the SQL syntax and try again.",
            })
        logger.exception("BQ dry run failed")
        return f"Error: Dry run failed — {e}"


# ---------------------------------------------------------------------------
# Tool: get_bq_table_schema
# ---------------------------------------------------------------------------

@mcp.tool()
def get_bq_table_schema(table: str) -> str:
    """Discover the schema (columns, types, descriptions) of a BigQuery table at runtime.

    Use this when you need to verify exact column names before writing a query,
    or when a static schema Resource might be outdated.

    Args:
        table: Fully qualified BQ table name (e.g. cie-costmanagement-803717.gcp.daily_usage_costs).
    """
    client = _init_bq_client()
    if not client:
        return "Error: BigQuery client not initialized. Check credentials and GCP_PROJECT_ID."

    clean_table = table.strip().strip("`")

    # Must reference our project
    if PROJECT_ID not in clean_table:
        return f"Error: Table must be in project {PROJECT_ID}."

    try:
        from google.cloud import bigquery as bq

        table_ref = client.get_table(clean_table)
        columns = []
        for field in table_ref.schema:
            col = {
                "name": field.name,
                "type": field.field_type,
                "mode": field.mode,
            }
            if field.description:
                col["description"] = field.description
            columns.append(col)

        return json.dumps({
            "table": clean_table,
            "column_count": len(columns),
            "total_rows": table_ref.num_rows,
            "total_bytes": table_ref.num_bytes,
            "size_gb": round((table_ref.num_bytes or 0) / (1024 ** 3), 2),
            "created": table_ref.created.isoformat() if table_ref.created else None,
            "modified": table_ref.modified.isoformat() if table_ref.modified else None,
            "columns": columns,
        }, default=str)

    except Exception as e:
        logger.exception("BQ schema discovery failed")
        return f"Error: Schema discovery failed — {e}"


# ---------------------------------------------------------------------------
# Resources: table schemas (static files)
# ---------------------------------------------------------------------------

@mcp.resource("schema://bq/azure/daily_costs")
def schema_azure_daily_costs() -> str:
    """Azure daily cost table schema — columns, types, cost/date column names."""
    return _load_resource_file("schemas/bq_azure_daily_costs.json")


@mcp.resource("schema://bq/aws/daily_costs")
def schema_aws_daily_costs() -> str:
    """AWS daily cost table schema — columns, types, cost/date column names."""
    return _load_resource_file("schemas/bq_aws_daily_costs.json")


@mcp.resource("schema://bq/gcp/daily_costs")
def schema_gcp_daily_costs() -> str:
    """GCP daily cost table schema — columns, types, cost/date column names."""
    return _load_resource_file("schemas/bq_gcp_daily_costs.json")


@mcp.resource("schema://bq/azure/utilization_metrics")
def schema_azure_utilization() -> str:
    """Azure utilization metrics table schema — for rightsizing analysis."""
    return _load_resource_file("schemas/bq_azure_utilization_metrics.json")


@mcp.resource("schema://bq/azure/recommendation_savings")
def schema_azure_recommendation_savings() -> str:
    """Azure recommendation savings tracking table — actioned recommendations and realized savings."""
    return _load_resource_file("schemas/bq_azure_recommendation_savings.json")


@mcp.resource("schema://bq/gcp/recommendations")
def schema_gcp_recommendations() -> str:
    """GCP recommendation table schema — enriched with business mappings. In reporting_data dataset."""
    return _load_resource_file("schemas/bq_gcp_recommendations.json")


@mcp.resource("schema://bq/gcp/pricing_export")
def schema_gcp_pricing_export() -> str:
    """GCP pricing catalog — list prices AND negotiated/contract prices per SKU. Join to costs via sku_id."""
    return _load_resource_file("schemas/bq_gcp_pricing_export.json")


# ---------------------------------------------------------------------------
# Resources: guides
# ---------------------------------------------------------------------------

@mcp.resource("guide://query-patterns")
def guide_query_patterns() -> str:
    """Common BigQuery SQL patterns for cost analysis — aggregation, comparison, trends, date handling per cloud."""
    return _load_resource_file("guides/query_patterns.md")


@mcp.resource("guide://cloud-taxonomy")
def guide_cloud_taxonomy() -> str:
    """Cross-cloud service mapping (EC2↔VM↔Compute Engine) and table locations (BQ vs SQL Server)."""
    return _load_resource_file("guides/cloud_taxonomy.json")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def cost_breakdown(cloud: str = "all", dimension: str = "service", period: str = "last 30 days") -> str:
    """Analyze cloud costs grouped by a dimension for a time period.

    Args:
        cloud: Cloud provider — aws, gcp, azure, or all.
        dimension: Grouping dimension — service, project, region, environment.
        period: Time period — e.g. 'last 30 days', 'March 2026', 'Q1 2026'.
    """
    return f"""Analyze {cloud} cloud costs grouped by {dimension} for {period}.

Steps:
1. Read the relevant schema resource(s) to get correct table/column names.
2. Read guide://query-patterns for SQL patterns.
3. Write and execute a BigQuery query.
4. Present results as:
   - Top 10 items by spend (table format)
   - Total spend for the period
   - Daily trend if period > 7 days
5. Flag any data quality issues (partial periods, nulls in group-by column).

Use the correct cost column per cloud (azure_cost / total_cost / total_cost_after_support)."""


@mcp.prompt()
def period_comparison(cloud: str = "all", metric: str = "total spend", period_a: str = "last month", period_b: str = "this month") -> str:
    """Compare a cost metric between two time periods.

    Args:
        cloud: Cloud provider — aws, gcp, azure, or all.
        metric: What to compare — total spend, service breakdown, project spend.
        period_a: First period (baseline).
        period_b: Second period (comparison).
    """
    return f"""Compare {metric} between '{period_a}' and '{period_b}' for {cloud} cloud.

Steps:
1. Read schema resources for correct table/column names.
2. Write a single query using CTEs for both periods.
3. For each period show:
   - Total spend
   - Top 5 items by spend
   - Percentage change per item (use SAFE_DIVIDE)
4. Highlight significant variances (>20% change).
5. Flag if either period is partial/incomplete."""


@mcp.prompt()
def anomaly_investigation(service: str = "", date: str = "", cloud: str = "all") -> str:
    """Investigate a cost anomaly for a specific service and date.

    Args:
        service: Service name showing the anomaly (optional — scan all if empty).
        date: Date of the anomaly (optional — scan recent 7 days if empty).
        cloud: Cloud provider — aws, gcp, azure, or all.
    """
    service_clause = f"for service '{service}'" if service else "across all services"
    date_clause = f"on {date}" if date else "over the last 7 days"

    return f"""Investigate the cost anomaly {service_clause} {date_clause} in {cloud} cloud.

Steps:
1. Query daily spend for the service over a 30-day window centered on the anomaly date.
2. Calculate the baseline (mean) and standard deviation from the surrounding days.
3. Report:
   - Anomaly date spend vs baseline ($ and %)
   - Z-score (how many standard deviations from mean)
   - Possible root causes: new resources, usage spike, pricing change, tag changes
4. Query spend breakdown by sub-dimensions (resource group, SKU, region) for the anomaly date vs baseline.
5. Recommend next steps: investigate specific resources, set up alerts, contact team owner."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
