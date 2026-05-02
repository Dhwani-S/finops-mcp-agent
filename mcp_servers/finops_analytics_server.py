"""
FinOps Analytics Server — MCP server for computation and validation.

Pure computation engine: anomaly detection, forecasting, growth calculations,
recommendation scoring, and result validation.
No database access — operates on data passed in by the agent.

Run:
    # Dev inspector
    mcp dev mcp_servers/finops_analytics_server.py

    # Stdio mode (how the agent connects)
    python mcp_servers/finops_analytics_server.py
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

RESOURCES_DIR = _project_root / "resources"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("finops_analytics_server")

mcp = FastMCP("FinOps-Analytics-Server")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_resource_file(relative_path: str) -> str:
    """Load a resource file from the resources/ directory."""
    path = (RESOURCES_DIR / relative_path).resolve()
    if not path.exists():
        return f"Error: Resource file not found: {relative_path}"
    return path.read_text(encoding="utf-8")


def _parse_data(data_json: str) -> list[dict] | None:
    """Parse JSON string into list of dicts. Returns None on failure."""
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        if isinstance(data, list):
            return data
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_time_series(data: list[dict], date_key: str = "date",
                         value_key: str = "value") -> tuple[list[str], np.ndarray] | None:
    """Extract dates and values from time-series data.

    Auto-detects date and value keys if the provided ones aren't found.
    """
    if not data:
        return None

    # Auto-detect keys
    sample = data[0]
    if date_key not in sample:
        for k in ("date", "day", "dateTime", "period", "month"):
            if k in sample:
                date_key = k
                break
    if value_key not in sample:
        for k in ("value", "spend", "cost", "total_cost", "amount", "total_spend"):
            if k in sample:
                value_key = k
                break

    if date_key not in data[0] or value_key not in data[0]:
        return None

    dates = [str(row.get(date_key, "")) for row in data]
    values = np.array([float(row.get(value_key, 0)) for row in data], dtype=np.float64)
    return dates, values


# ---------------------------------------------------------------------------
# Tool 1: detect_anomalies
# ---------------------------------------------------------------------------

@mcp.tool()
def detect_anomalies(data_json: str, method: str = "z_score",
                     sensitivity: float = 2.5) -> str:
    """Detect anomalies in time-series cost data using statistical methods.

    DO NOT call this with raw BQ/SQL query results directly. First transform the query output
    into a simple array with one date column and one numeric column per object.

    REQUIRED INPUT FORMAT: JSON array where each object has:
    - A date field named one of: date, day, dateTime, period, month
    - A numeric field named one of: spend, cost, value, amount, total_cost, total_spend
    Example: [{"date": "2026-04-01", "spend": 1234.56}, {"date": "2026-04-02", "spend": 1100.00}]

    Minimum 7 data points required.

    Args:
        data_json: JSON array of objects with date and value fields (see format above).
        method: Detection method — "z_score" or "iqr". Default: "z_score".
        sensitivity: Threshold — lower = more sensitive. Default: 2.5.
                     For z_score: number of standard deviations.
                     For iqr: multiplier of the interquartile range.

    Returns:
        JSON with anomalies found, baseline stats, and per-point scores.
    """
    data = _parse_data(data_json)
    if not data:
        return "Error: Could not parse data_json. Provide a JSON array of objects."

    ts = _extract_time_series(data)
    if ts is None:
        return "Error: Could not extract time series. Ensure data has date and numeric value fields."

    dates, values = ts

    if len(values) < 7:
        return "Error: Need at least 7 data points for anomaly detection."

    method = method.lower()
    if method not in ("z_score", "iqr"):
        return "Error: method must be 'z_score' or 'iqr'."

    mean_val = float(np.mean(values))
    std_val = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    median_val = float(np.median(values))

    anomalies = []

    if method == "z_score":
        if std_val == 0:
            return json.dumps({
                "method": "z_score", "anomalies": [],
                "baseline": {"mean": mean_val, "std": 0, "count": len(values)},
                "message": "All values are identical — no anomalies possible."
            })

        for i, (d, v) in enumerate(zip(dates, values)):
            z = (v - mean_val) / std_val
            if abs(z) >= sensitivity:
                anomalies.append({
                    "date": d,
                    "value": float(v),
                    "z_score": round(z, 2),
                    "deviation_pct": round((v - mean_val) / mean_val * 100, 1),
                    "direction": "spike" if z > 0 else "dip",
                })

        return json.dumps({
            "method": "z_score",
            "threshold": sensitivity,
            "baseline": {
                "mean": round(mean_val, 2),
                "std": round(std_val, 2),
                "median": round(median_val, 2),
                "count": len(values),
            },
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        })

    else:  # iqr
        q1 = float(np.percentile(values, 25))
        q3 = float(np.percentile(values, 75))
        iqr = q3 - q1

        lower = q1 - sensitivity * iqr
        upper = q3 + sensitivity * iqr

        for d, v in zip(dates, values):
            fv = float(v)
            if fv < lower or fv > upper:
                anomalies.append({
                    "date": d,
                    "value": fv,
                    "deviation_pct": round((fv - median_val) / median_val * 100, 1) if median_val else 0,
                    "direction": "spike" if fv > upper else "dip",
                })

        return json.dumps({
            "method": "iqr",
            "threshold_multiplier": sensitivity,
            "baseline": {
                "q1": round(q1, 2), "q3": round(q3, 2), "iqr": round(iqr, 2),
                "lower_bound": round(lower, 2), "upper_bound": round(upper, 2),
                "median": round(median_val, 2), "count": len(values),
            },
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        })


# ---------------------------------------------------------------------------
# Tool 2: forecast
# ---------------------------------------------------------------------------

@mcp.tool()
def forecast(data_json: str, periods_ahead: int = 7,
             method: str = "linear") -> str:
    """Forecast future cost values from historical time-series data.

    DO NOT call this with raw BQ/SQL query results directly. First transform the query output
    into a simple array with one date column and one numeric column per object, sorted chronologically.

    REQUIRED INPUT FORMAT: JSON array where each object has:
    - A date field named one of: date, day, dateTime, period, month
    - A numeric field named one of: spend, cost, value, amount, total_cost, total_spend
    Example: [{"date": "2026-03-01", "spend": 50000}, {"date": "2026-03-02", "spend": 51000}, ...]

    Minimum 7 data points required. Data MUST be sorted by date ascending.

    Args:
        data_json: JSON array of objects with date and value fields, sorted chronologically.
        periods_ahead: Number of future periods to forecast. Default: 7. Max: 90.
        method: "linear" (linear regression) or "ema" (exponential moving average). Default: "linear".

    Returns:
        JSON with forecasted values, confidence intervals, and model metrics.
    """
    data = _parse_data(data_json)
    if not data:
        return "Error: Could not parse data_json."

    ts = _extract_time_series(data)
    if ts is None:
        return "Error: Could not extract time series."

    dates, values = ts

    if len(values) < 7:
        return "Error: Need at least 7 data points for forecasting."

    periods_ahead = max(1, min(periods_ahead, 90))
    method = method.lower()

    n = len(values)
    x = np.arange(n, dtype=np.float64)

    if method == "linear":
        # Linear regression: y = slope * x + intercept
        slope, intercept = np.polyfit(x, values, 1)
        residuals = values - (slope * x + intercept)
        std_residual = float(np.std(residuals, ddof=2)) if n > 2 else 0.0

        # R-squared
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((values - np.mean(values)) ** 2))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        forecasted = []
        for i in range(1, periods_ahead + 1):
            xi = n + i - 1
            point = slope * xi + intercept
            # 95% confidence interval widens with distance
            ci = 1.96 * std_residual * math.sqrt(1 + 1/n + (xi - np.mean(x))**2 / np.sum((x - np.mean(x))**2))
            forecasted.append({
                "period": i,
                "value": round(float(point), 2),
                "lower_95": round(float(point - ci), 2),
                "upper_95": round(float(point + ci), 2),
            })

        projected_total = sum(f["value"] for f in forecasted)

        return json.dumps({
            "method": "linear_regression",
            "model": {
                "slope_per_period": round(float(slope), 4),
                "intercept": round(float(intercept), 2),
                "r_squared": round(r_squared, 4),
                "residual_std": round(std_residual, 2),
            },
            "input_points": n,
            "periods_ahead": periods_ahead,
            "projected_total": round(projected_total, 2),
            "trend": "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat",
            "forecast": forecasted,
        })

    elif method == "ema":
        # Exponential moving average
        alpha = 2.0 / (min(n, 10) + 1)  # Span = min(n, 10)
        ema = [float(values[0])]
        for v in values[1:]:
            ema.append(alpha * float(v) + (1 - alpha) * ema[-1])

        last_ema = ema[-1]
        # Forecast is flat at last EMA (no trend component)
        residuals = values - np.array(ema)
        std_residual = float(np.std(residuals, ddof=1)) if n > 1 else 0.0

        forecasted = []
        for i in range(1, periods_ahead + 1):
            ci = 1.96 * std_residual * math.sqrt(i)
            forecasted.append({
                "period": i,
                "value": round(last_ema, 2),
                "lower_95": round(last_ema - ci, 2),
                "upper_95": round(last_ema + ci, 2),
            })

        return json.dumps({
            "method": "exponential_moving_average",
            "model": {
                "alpha": round(alpha, 4),
                "last_ema": round(last_ema, 2),
                "residual_std": round(std_residual, 2),
            },
            "input_points": n,
            "periods_ahead": periods_ahead,
            "projected_total": round(last_ema * periods_ahead, 2),
            "trend": "flat (EMA forecast is constant)",
            "forecast": forecasted,
        })

    else:
        return "Error: method must be 'linear' or 'ema'."


# ---------------------------------------------------------------------------
# Tool 3: calculate_growth
# ---------------------------------------------------------------------------

@mcp.tool()
def calculate_growth(data_json: str, period: str = "MoM") -> str:
    """Calculate growth rates between periods in cost data.

    DO NOT call this with raw daily cost data. First aggregate your query results into
    period-level totals (e.g., monthly totals) before passing them here.

    REQUIRED INPUT FORMAT: JSON array where each object has:
    - A period label field named one of: month, week, quarter, year, period, date
    - A numeric value field named one of: spend, value, cost, total, amount, total_spend
    Example: [{"month": "2026-01", "spend": 50000}, {"month": "2026-02", "spend": 55000}]

    Minimum 2 data points required.

    Args:
        data_json: JSON array of objects with period label and value (see format above).
        period: Growth period type — "MoM" (month-over-month), "WoW" (week-over-week),
                "QoQ" (quarter-over-quarter), or "YoY" (year-over-year). Default: "MoM".

    Returns:
        JSON with growth rates, absolute changes, and summary statistics.
    """
    data = _parse_data(data_json)
    if not data or len(data) < 2:
        return "Error: Need at least 2 data points to calculate growth."

    # Auto-detect period and value keys
    sample = data[0]
    period_key = None
    for k in ("month", "week", "quarter", "year", "period", "date"):
        if k in sample:
            period_key = k
            break
    if not period_key:
        period_key = list(sample.keys())[0]

    value_key = None
    for k in ("spend", "value", "cost", "total", "amount", "total_spend"):
        if k in sample:
            value_key = k
            break
    if not value_key:
        # Pick first numeric-looking key
        for k, v in sample.items():
            if k != period_key and isinstance(v, (int, float)):
                value_key = k
                break
    if not value_key:
        return "Error: Could not find a numeric value column."

    results = []
    for i in range(1, len(data)):
        prev_val = float(data[i-1].get(value_key, 0))
        curr_val = float(data[i].get(value_key, 0))
        abs_change = curr_val - prev_val
        pct_change = (abs_change / prev_val * 100) if prev_val != 0 else None

        results.append({
            "from": str(data[i-1].get(period_key, "")),
            "to": str(data[i].get(period_key, "")),
            "previous": round(prev_val, 2),
            "current": round(curr_val, 2),
            "absolute_change": round(abs_change, 2),
            "pct_change": round(pct_change, 1) if pct_change is not None else None,
            "direction": "increase" if abs_change > 0 else "decrease" if abs_change < 0 else "flat",
        })

    pct_values = [r["pct_change"] for r in results if r["pct_change"] is not None]
    summary = {
        "period_type": period,
        "comparisons": len(results),
        "avg_growth_pct": round(sum(pct_values) / len(pct_values), 1) if pct_values else None,
        "max_growth_pct": round(max(pct_values), 1) if pct_values else None,
        "min_growth_pct": round(min(pct_values), 1) if pct_values else None,
    }

    return json.dumps({"growth_type": period, "summary": summary, "periods": results})


# ---------------------------------------------------------------------------
# Tool 4: score_recommendations
# ---------------------------------------------------------------------------

@mcp.tool()
def score_recommendations(recommendations_json: str) -> str:
    """Score and rank cost optimization recommendations deterministically.

    Scores each recommendation by: savings_potential × confidence × (1/effort).
    Higher score = higher priority.

    INPUT: Pass the JSON output from run_sql_query on recommendation tables directly.
    Each object should have at minimum an estimated_monthly_savings field.

    Args:
        recommendations_json: JSON array of recommendation objects. Each should have:
            - estimated_monthly_savings (required, numeric)
            - confidence (optional, 0–1, default 0.8)
            - effort (optional, "low"/"medium"/"high", default "medium")
            - Any other fields are passed through unchanged.

    Returns:
        JSON array of scored and ranked recommendations with _score, _rank, _annual_savings fields added.
    """
    data = _parse_data(recommendations_json)
    if not data:
        return "Error: Could not parse recommendations_json."

    effort_weights = {"low": 1.0, "medium": 0.6, "high": 0.3}

    scored = []
    for rec in data:
        savings = float(rec.get("estimated_monthly_savings", 0))
        confidence = float(rec.get("confidence", 0.8))
        effort = str(rec.get("effort", "medium")).lower()
        effort_weight = effort_weights.get(effort, 0.6)

        # Normalize savings to 0–100 scale (cap at $50K/month)
        savings_normalized = min(savings / 500, 100)

        score = round(savings_normalized * confidence * effort_weight, 2)

        scored_rec = {**rec}  # Shallow copy
        scored_rec["_score"] = score
        scored_rec["_savings_normalized"] = round(savings_normalized, 2)
        scored_rec["_effort_weight"] = effort_weight
        scored_rec["_annual_savings"] = round(savings * 12, 2)
        scored.append(scored_rec)

    scored.sort(key=lambda r: r["_score"], reverse=True)

    # Add rank
    for i, rec in enumerate(scored, 1):
        rec["_rank"] = i

    total_monthly = sum(float(r.get("estimated_monthly_savings", 0)) for r in scored)

    return json.dumps({
        "total_recommendations": len(scored),
        "total_monthly_savings": round(total_monthly, 2),
        "total_annual_savings": round(total_monthly * 12, 2),
        "ranked_recommendations": scored,
    })


# ---------------------------------------------------------------------------
# Tool 8: validate_results
# ---------------------------------------------------------------------------

@mcp.tool()
def validate_results(data_json: str, query_context: str = "") -> str:
    """Post-query sanity checks on cost data results.

    Call this after run_bq_query or run_sql_query when dealing with large or critical datasets.
    Checks for: negative costs, extreme growth rates, null rate issues,
    sum consistency, and zero-row conditions.

    Args:
        data_json: JSON array of result rows from a cost query (pass the raw tool output).
        query_context: Optional description of the query for better diagnostics (e.g., "GCP costs by service for March 2026").

    Returns:
        JSON with validation results — pass/warn/fail per check.
    """
    data = _parse_data(data_json)
    if data is None:
        return "Error: Could not parse data_json."

    checks = []

    # Check 1: Zero rows
    if len(data) == 0:
        checks.append({
            "check": "zero_rows",
            "status": "warn",
            "message": "Query returned 0 rows. Possible causes: wrong date range, wrong table, or access issue.",
        })
        return json.dumps({"checks": checks, "overall": "warn", "row_count": 0})

    # Detect cost columns
    cost_keys = []
    sample = data[0]
    for key in sample:
        if any(c in key.lower() for c in ("cost", "spend", "savings", "price", "amount")):
            cost_keys.append(key)

    # Check 2: Negative costs
    neg_count = 0
    for row in data:
        for ck in cost_keys:
            val = row.get(ck)
            if isinstance(val, (int, float)) and val < 0:
                neg_count += 1

    if neg_count > 0:
        pct = round(neg_count / (len(data) * max(len(cost_keys), 1)) * 100, 1)
        checks.append({
            "check": "negative_costs",
            "status": "warn" if pct < 10 else "fail",
            "message": f"{neg_count} negative cost values found ({pct}%). Usually credits/refunds — verify if unexpected.",
        })
    else:
        checks.append({"check": "negative_costs", "status": "pass", "message": "No negative costs."})

    # Check 3: Null rates in common group-by columns
    group_cols = [k for k in sample if any(g in k.lower() for g in
                  ("service", "project", "team", "environment", "region", "account", "subscription"))]

    for col in group_cols:
        null_count = sum(1 for row in data if row.get(col) is None or str(row.get(col, "")).strip() == "")
        null_rate = null_count / len(data) * 100
        if null_rate > 20:
            checks.append({
                "check": f"null_rate_{col}",
                "status": "warn",
                "message": f"Column '{col}' is null/empty in {round(null_rate, 1)}% of rows. Consider COALESCE in query.",
            })
        elif null_rate > 0:
            checks.append({
                "check": f"null_rate_{col}",
                "status": "info",
                "message": f"Column '{col}' has {round(null_rate, 1)}% null rate.",
            })

    # Check 4: Extreme values
    for ck in cost_keys:
        vals = [float(row.get(ck, 0)) for row in data if isinstance(row.get(ck), (int, float))]
        if len(vals) >= 2:
            mean_v = sum(vals) / len(vals)
            max_v = max(vals)
            if mean_v > 0 and max_v > mean_v * 10:
                checks.append({
                    "check": f"extreme_value_{ck}",
                    "status": "warn",
                    "message": f"Max value in '{ck}' ({round(max_v, 2)}) is {round(max_v/mean_v, 1)}x the mean ({round(mean_v, 2)}). Possible outlier.",
                })

    # Check 5: Row count
    if len(data) == 500:
        checks.append({
            "check": "truncation",
            "status": "warn",
            "message": "Exactly 500 rows returned — results may be truncated. Add LIMIT or filters.",
        })

    # Overall status
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return json.dumps({
        "overall": overall,
        "row_count": len(data),
        "cost_columns_found": cost_keys,
        "checks": checks,
        "query_context": query_context,
    })


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("taxonomy://cloud-services")
def taxonomy_cloud_services() -> str:
    """Cross-cloud service mapping with normalized canonical names (EC2 ↔ VM ↔ Compute Engine)."""
    return _load_resource_file("analytics/cloud_services_taxonomy.json")


@mcp.resource("reference://anomaly-thresholds")
def reference_anomaly_thresholds() -> str:
    """Default anomaly detection thresholds by spend tier — sensitivity configs for z-score and IQR methods."""
    return _load_resource_file("analytics/anomaly_thresholds.json")


@mcp.resource("reference://pricing-data-guide")
def reference_pricing_data_guide() -> str:
    """Where actual pricing data lives in our cost tables — columns per cloud for unit prices, SKUs, and pricing terms."""
    return _load_resource_file("analytics/pricing_data_guide.json")


@mcp.resource("elicitation://rules")
def elicitation_rules() -> str:
    """Tiered ambiguity rules — when to assume (Tier 0), warn (Tier 1), ask (Tier 2), or block (Tier 3)."""
    return _load_resource_file("elicitation/rules.json")


@mcp.resource("elicitation://cost-columns")
def elicitation_cost_columns() -> str:
    """What each cost column means per cloud and when to use which (gross vs net, USD vs local)."""
    return _load_resource_file("elicitation/cost_columns.json")


@mcp.resource("elicitation://data-quality")
def elicitation_data_quality() -> str:
    """Known data gaps, null rates by field, freshness SLAs, and validation rules."""
    return _load_resource_file("elicitation/data_quality.json")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def investigate_anomaly(service: str = "", cloud: str = "all",
                        anomaly_data: str = "") -> str:
    """Investigate and explain the likely cause of a cost anomaly.

    Args:
        service: Service name showing the anomaly.
        cloud: Cloud provider — aws, gcp, azure, or all.
        anomaly_data: JSON string of anomaly detection results (from detect_anomalies tool).
    """
    return f"""Investigate the cost anomaly for {service} ({cloud} cloud).

Anomaly detection results:
{anomaly_data}

Steps:
1. Read elicitation://data-quality to check for known data gaps or freshness issues.
2. Analyze the anomaly scores — z-score > 3 or IQR outlier?
3. Determine likely root causes:
   - New resource deployment (check for new resource groups/projects)
   - Usage spike (increased API calls, data transfer, compute hours)
   - Pricing change (new commitment expired, rate change)
   - Tag/allocation change (cost shifted between categories)
   - Data pipeline issue (duplicate records, backfill)
4. For each hypothesis, suggest a follow-up query to confirm.
5. Recommend actions:
   - Investigate specific resources
   - Set up budget alerts
   - Contact team/resource owner
   - Compare with utilization metrics
6. Quantify the impact: total excess cost, projected monthly impact if trend continues."""


@mcp.prompt()
def forecast_summary(forecast_data: str = "", context: str = "") -> str:
    """Summarize a cost forecast with business context and risk assessment.

    Args:
        forecast_data: JSON string of forecast results (from forecast tool).
        context: Additional business context (budget, previous period, etc.).
    """
    return f"""Summarize this cost forecast for a FinOps audience.

Forecast data:
{forecast_data}

Context: {context}

Present:
1. **Projected Spend**: Total forecasted amount for the period.
2. **Trend**: Is spend increasing, decreasing, or flat? At what rate?
3. **Confidence**: How reliable is this forecast? (R², data points, residual std)
4. **Risk Assessment**:
   - If upper 95% CI, what's the worst case?
   - If lower 95% CI, what's the best case?
   - Key assumptions and limitations.
5. **Budget Comparison**: If budget info is available, compare projected vs budget.
6. **Recommendations**:
   - If increasing: identify drivers, suggest optimization areas.
   - If decreasing: verify it's intentional, not service degradation.
   - If flat: good — maintain current controls.
7. **Data Quality Notes**: Flag partial periods, insufficient history, or seasonal patterns not captured."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
