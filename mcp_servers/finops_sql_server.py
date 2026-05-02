"""
FinOps SQL Server — MCP server for Azure SQL / SQL Server data access.

Serves recommendations, K8s costs, and observability data from SQL Server.
Dynamic schema discovery since SQL Server tables change more frequently than BQ.
All queries are read-only with SQL guardrails and row limits.

Run:
    # Dev inspector
    mcp dev mcp_servers/finops_sql_server.py

    # Stdio mode (how the agent connects)
    python mcp_servers/finops_sql_server.py
"""

from __future__ import annotations

import decimal
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST", "")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB", "")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER", "")
SQL_SERVER_PASS = os.getenv("SQL_SERVER_PASS", "")

RESOURCES_DIR = _project_root / "resources"
MAX_RESULT_ROWS = 500
QUERY_TIMEOUT_SECONDS = 30

# DML/DDL keywords that must never appear in a query
_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE|EXEC|EXECUTE|xp_|sp_)\b",
    re.IGNORECASE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("finops_sql_server")

mcp = FastMCP("FinOps-SQL-Server")

# ---------------------------------------------------------------------------
# SQL Server client (lazy — fails gracefully if credentials missing)
# ---------------------------------------------------------------------------

_sql_conn = None


def _get_connection():
    """Get or create a pymssql connection. Returns connection or None."""
    global _sql_conn
    if _sql_conn is not None:
        try:
            _sql_conn.cursor().execute("SELECT 1")
            return _sql_conn
        except Exception:
            _sql_conn = None

    if not all([SQL_SERVER_HOST, SQL_SERVER_DB, SQL_SERVER_USER, SQL_SERVER_PASS]):
        logger.error("SQL Server credentials not configured. Check .env file.")
        return None

    try:
        import pymssql

        _sql_conn = pymssql.connect(
            server=SQL_SERVER_HOST,
            database=SQL_SERVER_DB,
            user=SQL_SERVER_USER,
            password=SQL_SERVER_PASS,
            login_timeout=10,
            timeout=QUERY_TIMEOUT_SECONDS,
            as_dict=True,
        )
        logger.info("SQL Server connection established: %s/%s", SQL_SERVER_HOST, SQL_SERVER_DB)
        return _sql_conn
    except Exception as e:
        logger.error("Could not connect to SQL Server: %s", e)
        _sql_conn = None
        return None


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
    """Validate a T-SQL query. Returns error message or None if valid."""
    clean = sql.strip()

    # Must start with SELECT or WITH
    if not re.match(r"^(SELECT|WITH)\s", clean, re.IGNORECASE):
        return "Only SELECT/WITH statements are permitted."

    # Strip string literals before keyword check so values like 'Delete' don't trigger
    no_strings = re.sub(r"'[^']*'", "''", clean)

    # Reject DML/DDL/dangerous keywords
    match = _BLOCKED_KEYWORDS.search(no_strings)
    if match:
        return f"Blocked keyword detected: {match.group(0).upper()}"

    # Reject multi-statement (semicolons not at the very end)
    stripped = clean.rstrip(";").strip()
    if ";" in stripped:
        return "Multi-statement queries are not allowed."

    return None


# Columns that indicate the query is scoped to a specific team/project/owner
_SCOPE_FILTERS_SQL = re.compile(
    r"\b(project_name|subscription_name|subscription_id|resource_group"
    r"|owner|team|business_unit|environment|core_id|user_name"
    r"|linked_account_id|linked_account_name)\b",
    re.IGNORECASE,
)

# Patterns that indicate the query aggregates cost data
_COST_AGGREGATION_SQL = re.compile(
    r"\b(SUM|AVG|TOTAL)\s*\("
    r"|\b(total_cost|estimated_monthly_savings|cost|savings|amount)\b",
    re.IGNORECASE,
)


def _check_scope_sql(sql: str) -> str | None:
    """Reject aggregate cost/savings queries that have no scope filter."""
    clean = sql.strip()

    if not _COST_AGGREGATION_SQL.search(clean):
        return None

    where_match = re.search(r"\bWHERE\b(.+)", clean, re.IGNORECASE | re.DOTALL)
    if where_match:
        where_clause = where_match.group(1)
        if _SCOPE_FILTERS_SQL.search(where_clause):
            return None

    group_match = re.search(r"\bGROUP\s+BY\b(.+?)(?:ORDER|HAVING|$)", clean, re.IGNORECASE | re.DOTALL)
    if group_match:
        group_clause = group_match.group(1)
        if _SCOPE_FILTERS_SQL.search(group_clause):
            return None

    return (
        "SCOPE REQUIRED: This query aggregates cost/savings data across the entire organization "
        "without filtering by project, team, or owner. Ask the user which scope they want:\n"
        "1. Organization-wide (confirm explicitly)\n"
        "2. A specific project or subscription\n"
        "3. A specific team or owner\n\n"
        "If the user confirms organization-wide, re-call run_sql_query with "
        "org_wide_confirmed=true and the same SQL."
    )


def _serialize_value(value):
    """Convert SQL Server value to JSON-serializable type."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _serialize_row(row: dict) -> dict:
    """Convert a SQL Server result row to JSON-serializable dict."""
    return {k: _serialize_value(v) for k, v in row.items()}


# Column name validation — alphanumeric + underscore only
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Tool 1: list_dimension_values
# ---------------------------------------------------------------------------

@mcp.tool()
def sql_list_dimension_values(
    table_name: str,
    column: str,
    filter_term: str = "",
    schema_name: str = "reporting",
    limit: int = 25,
) -> str:
    """Look up distinct values for a column in a SQL Server table.

    DATA SCOPE: Azure/AWS recommendations, K8s costs, observability costs, identity mappings.
    DO NOT USE for: GCP/AWS/Azure daily cost data — use bq_list_dimension_values instead.

    Use this BEFORE writing run_sql_query to find exact entity values in the data.
    Returns distinct values sorted by frequency (most common first).

    WHEN TO USE:
    - User asks about recommendations, K8s costs, or observability data
    - You need to verify subscription names, resource types, or other entities in SQL Server tables
    - User's term is vague and might match multiple entries

    Args:
        table_name: Table name (e.g. azure_recommendations, k8_cost_tracking_integrated).
        column: Column name to look up distinct values for (e.g. project_name, service_name).
        filter_term: Optional text filter — returns only values containing this term (case-insensitive). Leave empty for all values.
        schema_name: Schema name. Default: "reporting". Use "dbo" for K8s tables.
        limit: Max number of distinct values to return. Default 25.
    """
    conn = _get_connection()
    if not conn:
        return "Error: SQL Server connection not available. Check credentials."

    # Validate identifiers — strict alphanumeric to prevent injection
    if not _VALID_IDENTIFIER.match(schema_name):
        return "Error: Invalid schema_name. Use only letters, numbers, and underscores."
    if not _VALID_IDENTIFIER.match(table_name):
        return "Error: Invalid table_name. Use only letters, numbers, and underscores."
    if not _VALID_IDENTIFIER.match(column):
        return "Error: Invalid column name. Use only letters, numbers, and underscores."

    limit = max(1, min(limit, 100))

    try:
        cursor = conn.cursor(as_dict=True)

        if filter_term:
            sql = (
                f"SELECT TOP {limit} [{column}] AS value, COUNT(*) AS row_count "
                f"FROM [{schema_name}].[{table_name}] "
                f"WHERE [{column}] LIKE %s "
                f"GROUP BY [{column}] "
                f"ORDER BY row_count DESC"
            )
            cursor.execute(sql, (f"%{filter_term}%",))
        else:
            sql = (
                f"SELECT TOP {limit} [{column}] AS value, COUNT(*) AS row_count "
                f"FROM [{schema_name}].[{table_name}] "
                f"GROUP BY [{column}] "
                f"ORDER BY row_count DESC"
            )
            cursor.execute(sql)

        rows = [{"value": _serialize_value(row["value"]), "row_count": row["row_count"]} for row in cursor.fetchall()]

        if not rows:
            msg = f"No values found for column '{column}' in [{schema_name}].[{table_name}]"
            if filter_term:
                msg += f" matching '{filter_term}'"
            return msg

        output = {
            "table": f"[{schema_name}].[{table_name}]",
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
# Tool 2: run_sql_query
# ---------------------------------------------------------------------------

@mcp.tool()
def run_sql_query(sql: str, org_wide_confirmed: bool = False) -> str:
    """Execute a read-only T-SQL query against the FinOps SQL Server database.

    DATA SCOPE: Azure/AWS recommendations, K8s costs, observability costs, identity mappings.
    DO NOT USE for: GCP/AWS/Azure daily cost data — use run_bq_query instead.

    PREREQUISITE: You MUST call get_table_schema or sql_list_dimension_values first to confirm
    exact column names and entity values. Do NOT guess column names.

    Returns results as JSON (max 500 rows). Only SELECT/WITH statements allowed.
    Use [schema].[table] notation (e.g. [reporting].[azure_recommendations]).

    SYNTAX REMINDERS:
    - Use TOP N (not LIMIT N — that's BigQuery)
    - Use LIKE for pattern matching (not REGEXP)
    - Date functions: DATEADD, DATEDIFF, GETDATE(), CAST(x AS DATE)

    Args:
        sql: T-SQL query string.
        org_wide_confirmed: Set to true ONLY after the user has explicitly confirmed they want
            organization-wide data (not scoped to a project/team/owner). Default false.
    """
    conn = _get_connection()
    if not conn:
        return "Error: SQL Server connection not available. Check credentials."

    error = _validate_sql(sql)
    if error:
        logger.warning("SQL validation failed: %s", error)
        return f"Error: {error}"

    # Scope enforcement — reject unscoped org-wide cost aggregations
    if not org_wide_confirmed:
        scope_error = _check_scope_sql(sql)
        if scope_error:
            logger.warning("Scope check failed for query")
            return f"Error: {scope_error}"

    try:
        cursor = conn.cursor(as_dict=True)
        start = time.time()
        cursor.execute(sql.strip().rstrip(";"))
        rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
        elapsed = time.time() - start

        serialized = [_serialize_row(row) for row in rows[:MAX_RESULT_ROWS]]
        logger.info("SQL query returned %d rows in %.1fs", len(serialized), elapsed)

        if not serialized:
            return "Query executed successfully but returned 0 rows."

        truncated = len(rows) > MAX_RESULT_ROWS
        output = json.dumps(serialized, indent=None)
        if truncated:
            output += f"\n[Truncated to {MAX_RESULT_ROWS} rows]"
        return output

    except Exception as e:
        logger.exception("SQL Server query failed")
        return f"Error: Query failed — {e}"


# ---------------------------------------------------------------------------
# Tool 2: get_table_schema
# ---------------------------------------------------------------------------

@mcp.tool()
def get_table_schema(table_name: str, schema_name: str = "reporting") -> str:
    """Discover the schema (columns, types, nullable) of a SQL Server table.

    Use this before writing queries to learn the exact column names and types.

    Args:
        table_name: Table name (e.g. "azure_recommendations").
        schema_name: Schema name. Default: "reporting". Use "dbo" for K8s tables without schema prefix.
    """
    conn = _get_connection()
    if not conn:
        return "Error: SQL Server connection not available. Check credentials."

    # Validate inputs — only allow alphanumeric + underscore
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema_name):
        return "Error: Invalid schema_name. Use alphanumeric characters and underscores only."
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        return "Error: Invalid table_name. Use alphanumeric characters and underscores only."

    try:
        cursor = conn.cursor(as_dict=True)
        # Use INFORMATION_SCHEMA for safe, injection-proof schema discovery
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH, "
            "NUMERIC_PRECISION, NUMERIC_SCALE, COLUMN_DEFAULT "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (schema_name, table_name),
        )
        columns = cursor.fetchall()

        if not columns:
            return f"Error: Table [{schema_name}].[{table_name}] not found or has no columns."

        result = {
            "schema": schema_name,
            "table": table_name,
            "fully_qualified": f"[{schema_name}].[{table_name}]",
            "column_count": len(columns),
            "columns": [
                {
                    "name": col["COLUMN_NAME"],
                    "type": col["DATA_TYPE"],
                    "nullable": col["IS_NULLABLE"] == "YES",
                    "max_length": col["CHARACTER_MAXIMUM_LENGTH"],
                }
                for col in columns
            ],
        }
        return json.dumps(result)

    except Exception as e:
        logger.exception("Schema discovery failed")
        return f"Error: Schema discovery failed — {e}"


# ---------------------------------------------------------------------------
# Tool 4: lookup_identity
# ---------------------------------------------------------------------------

@mcp.tool()
def lookup_identity(
    search_term: str,
    search_by: str = "name",
) -> str:
    """Look up user-to-project mappings from the identity table.

    Use this when a user asks about a person's projects, costs by person name,
    or wants to find which GCP/cloud projects belong to a specific user.

    Returns: core_id, user name, and associated project names.

    Args:
        search_term: The value to search for (person name, core_id, or project name).
        search_by: What field to search. One of: "name", "core_id", "project".
                   - "name": search by person name (partial match)
                   - "core_id": search by exact core_id (e.g. "PWFN83")
                   - "project": search by project name (partial match)
    """
    conn = _get_connection()
    if not conn:
        return "Error: SQL Server connection not available. Check credentials."

    allowed_fields = {
        "name": ("user_name", True),
        "core_id": ("core_id", False),
        "project": ("project_name", True),
    }

    if search_by not in allowed_fields:
        return f"Error: search_by must be one of: {', '.join(allowed_fields.keys())}"

    column, use_like = allowed_fields[search_by]

    try:
        cursor = conn.cursor(as_dict=True)

        if use_like:
            sql = (
                "SELECT DISTINCT core_id, user_name, project_name "
                "FROM [cost_management].[anomaly_cost_email_subscribers] "
                f"WHERE [{column}] LIKE %s "
                "ORDER BY user_name, project_name"
            )
            cursor.execute(sql, (f"%{search_term}%",))
        else:
            sql = (
                "SELECT DISTINCT core_id, user_name, project_name "
                "FROM [cost_management].[anomaly_cost_email_subscribers] "
                f"WHERE [{column}] = %s "
                "ORDER BY user_name, project_name"
            )
            cursor.execute(sql, (search_term,))

        rows = cursor.fetchmany(100)
        serialized = [_serialize_row(row) for row in rows]

        if not serialized:
            return f"No identity records found for {search_by}='{search_term}'"

        output = {
            "search_by": search_by,
            "search_term": search_term,
            "results_count": len(serialized),
            "records": serialized,
        }
        return json.dumps(output, indent=None, default=str)

    except Exception as e:
        logger.exception("Identity lookup failed")
        return f"Error: Identity lookup failed — {e}"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("schema://sql/available-tables")
def schema_available_tables() -> str:
    """List of SQL Server tables the agent can query — schemas, names, and purposes."""
    tables = {
        "description": "Available SQL Server tables",
        "connection": {
            "server": "(configured via env)",
            "database": "(configured via env)",
        },
        "tables": [
            {"schema": "reporting", "table": "azure_recommendations", "purpose": "Azure Advisor recommendations (cost, security, performance)"},
            {"schema": "reporting", "table": "aws_recommendations", "purpose": "AWS recommendations (rightsizing, RI, savings plans)"},
            {"schema": "reporting", "table": "azure_reservation_recommendations", "purpose": "Azure RI recommendations (subscription scope)"},
            {"schema": "reporting", "table": "azure_reservation_recommendations_rg", "purpose": "Azure RI recommendations (resource group scope)"},
            {"schema": "reporting", "table": "azure_savings_plan_recommendations", "purpose": "Azure Savings Plan recommendations"},
            {"schema": "dbo", "table": "k8_cost_tracking_integrated", "purpose": "Azure K8s costs (core hours + storage)"},
            {"schema": "reporting", "table": "aws_k8_cost_tracking_sync", "purpose": "AWS K8s costs"},
            {"schema": "reporting", "table": "gcp_k8_cost_tracking_tf", "purpose": "GCP K8s costs"},
            {"schema": "reporting", "table": "exp_centralized_cost_tracking", "purpose": "Centralized observability cost tracking"},
            {"schema": "reporting", "table": "obs_cpe_env_daily_cost", "purpose": "CPE environment daily costs"},
            {"schema": "reporting", "table": "azure_cpe_env_daily_cost", "purpose": "Azure CPE environment daily costs"},
            {"schema": "reporting", "table": "aws_daily_saving_reservation_costs", "purpose": "AWS daily savings/reservation costs"},
            {"schema": "cost_management", "table": "anomaly_cost_email_subscribers", "purpose": "Identity mapping: core_id → project_name (user ownership)"},
        ],
        "usage_note": "Use get_table_schema tool to discover columns before writing queries. Schemas change — don't assume column names.",
    }
    return json.dumps(tables, indent=2)


@mcp.resource("guide://tsql-patterns")
def guide_tsql_patterns() -> str:
    """T-SQL query patterns for FinOps — date handling, aggregation, and key syntax differences from BigQuery."""
    return _load_resource_file("guides/tsql_patterns.md")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def sql_exploration(table: str = "reporting.azure_recommendations") -> str:
    """Explore a SQL Server table: row count, sample data, and column distributions.

    Args:
        table: Fully qualified table name with schema (e.g. "reporting.azure_recommendations").
    """
    parts = table.split(".", 1)
    schema = parts[0] if len(parts) > 1 else "reporting"
    tbl = parts[1] if len(parts) > 1 else parts[0]

    return f"""Explore the SQL Server table [{schema}].[{tbl}].

Steps:
1. Use get_table_schema('{tbl}', '{schema}') to discover all columns and types.
2. Get the row count: SELECT COUNT(*) AS row_count FROM [{schema}].[{tbl}]
3. Get a sample: SELECT TOP 5 * FROM [{schema}].[{tbl}]
4. For date columns, find the date range:
   SELECT MIN(dateTime) AS earliest, MAX(dateTime) AS latest FROM [{schema}].[{tbl}]
5. For key categorical columns, show distinct value counts:
   SELECT column_name, COUNT(*) AS cnt FROM [{schema}].[{tbl}] GROUP BY column_name ORDER BY cnt DESC
6. Present a summary:
   - Table shape (rows × columns)
   - Date range covered
   - Key categorical distributions
   - Sample rows
   - Notable patterns (nulls, skew, data quality)

Read guide://tsql-patterns for T-SQL syntax reference."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
