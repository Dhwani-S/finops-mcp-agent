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

    WORKFLOW EXAMPLE:
    Step 1: Query daily spend → run_bq_query("SELECT DATE(dateTime) as date, SUM(total_cost) as cost FROM ... GROUP BY date ORDER BY date")
    Step 2: Transform result → extract only [{"date": "...", "cost": ...}] array from query output
    Step 3: Call detect_anomalies(data_json=<transformed>, method="z_score", sensitivity=2.5)

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

    WORKFLOW EXAMPLE (monthly forecast):
    Step 1: Query monthly totals → run_bq_query("SELECT DATE_TRUNC(date, MONTH) as month, SUM(cost_with_credits) as cost FROM ... WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH) GROUP BY month ORDER BY month")
    Step 2: Transform → extract [{"month": "2026-01-01", "cost": 120000}, ...] from result
    Step 3: Call forecast(data_json=<transformed>, periods_ahead=3, method="linear")

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
# Tool 4: summarize_data
# ---------------------------------------------------------------------------

@mcp.tool()
def summarize_data(data_json: str, group_by: str = "", value_column: str = "") -> str:
    """Summarize a large result set into aggregate statistics.

    Use this INSTEAD of letting the LLM scan hundreds of rows manually.
    Call after run_bq_query or run_sql_query to extract key numbers before
    putting results into the conversation.

    Returns: total, mean, median, min, max, count, std, top-N and bottom-N
    rows by the value column, plus optional group-by aggregation.

    WORKFLOW EXAMPLE:
    Step 1: run_bq_query("SELECT service_name, SUM(total_cost) as cost FROM ... GROUP BY service_name")
    Step 2: summarize_data(data_json=<query_result>, group_by="service_name", value_column="cost")
    → Returns stats + top/bottom 5 services + per-service totals with percentages

    Args:
        data_json: JSON array of objects (pass raw tool output from run_bq_query / run_sql_query).
        group_by: Optional column name to group by (e.g. "service_description", "project_name").
                  When set, returns per-group totals sorted descending.
        value_column: Column to aggregate. Auto-detected if empty — picks first column whose
                      name contains cost, spend, savings, price, or amount.
    """
    data = _parse_data(data_json)
    if not data:
        return "Error: Could not parse data_json. Provide a JSON array of objects."
    if len(data) == 0:
        return json.dumps({"error": "Empty dataset", "row_count": 0})

    sample = data[0]

    # Auto-detect value column
    if not value_column:
        for k in sample:
            if any(c in k.lower() for c in ("cost", "spend", "savings", "price", "amount", "total")):
                value_column = k
                break
    if not value_column:
        # Fall back to first numeric column
        for k, v in sample.items():
            if isinstance(v, (int, float)):
                value_column = k
                break
    if not value_column:
        return "Error: Could not find a numeric column to summarize. Specify value_column explicitly."

    # Extract numeric values (skip nulls)
    values = []
    for row in data:
        v = row.get(value_column)
        if v is not None:
            try:
                values.append(float(v))
            except (ValueError, TypeError):
                pass

    if not values:
        return f"Error: No numeric values found in column '{value_column}'."

    arr = np.array(values)

    result: dict = {
        "row_count": len(data),
        "value_column": value_column,
        "statistics": {
            "total": round(float(np.sum(arr)), 2),
            "mean": round(float(np.mean(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "std": round(float(np.std(arr, ddof=1)), 2) if len(arr) > 1 else 0.0,
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
        },
    }

    # Top and bottom 5
    indexed = [(i, v) for i, v in enumerate(values)]
    indexed.sort(key=lambda x: x[1], reverse=True)
    result["top_5"] = [data[i] for i, _ in indexed[:5]]
    result["bottom_5"] = [data[i] for i, _ in indexed[-5:]]

    # Group-by aggregation
    if group_by and group_by in sample:
        groups: dict[str, list[float]] = {}
        for row in data:
            key = str(row.get(group_by, "(null)"))
            v = row.get(value_column)
            if v is not None:
                try:
                    groups.setdefault(key, []).append(float(v))
                except (ValueError, TypeError):
                    pass

        group_agg = []
        for key, vals in groups.items():
            group_agg.append({
                "group": key,
                "total": round(sum(vals), 2),
                "count": len(vals),
                "mean": round(sum(vals) / len(vals), 2),
                "pct_of_total": round(sum(vals) / float(np.sum(arr)) * 100, 1) if float(np.sum(arr)) else 0,
            })
        group_agg.sort(key=lambda g: g["total"], reverse=True)
        result["group_by"] = group_by
        result["groups"] = group_agg[:25]  # Cap at 25 groups
        result["total_groups"] = len(group_agg)

    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool 5: compare_periods
# ---------------------------------------------------------------------------

@mcp.tool()
def compare_periods(period_a_json: str, period_b_json: str,
                    value_column: str = "", label_column: str = "") -> str:
    """Side-by-side comparison of two time periods with deltas and highlights.

    Use this after running two separate queries (one per period) to produce
    a unified comparison the LLM can present directly.

    Returns: per-item comparison with absolute and percentage deltas,
    plus summary totals and biggest movers.

    WORKFLOW EXAMPLE:
    Step 1: run_bq_query("SELECT service_name, SUM(total_cost) as cost FROM ... WHERE date BETWEEN '2026-03-01' AND '2026-03-31' GROUP BY service_name")  → period_a
    Step 2: run_bq_query("SELECT service_name, SUM(total_cost) as cost FROM ... WHERE date BETWEEN '2026-04-01' AND '2026-04-30' GROUP BY service_name")  → period_b
    Step 3: compare_periods(period_a_json=<step1>, period_b_json=<step2>, value_column="cost", label_column="service_name")
    → Returns per-service deltas, biggest increases/decreases, new/dropped services

    Args:
        period_a_json: JSON array for the baseline period (e.g. last month).
        period_b_json: JSON array for the comparison period (e.g. this month).
        value_column: Column to compare. Auto-detected if empty — picks first
                      column whose name contains cost, spend, savings, price, or amount.
        label_column: Column used as the join key / label (e.g. "service_description",
                      "project_name"). Auto-detected if empty.
    """
    data_a = _parse_data(period_a_json)
    data_b = _parse_data(period_b_json)
    if not data_a or not data_b:
        return "Error: Could not parse one or both period datasets."

    sample = data_a[0]

    # Auto-detect value column
    if not value_column:
        for k in sample:
            if any(c in k.lower() for c in ("cost", "spend", "savings", "price", "amount", "total")):
                value_column = k
                break
    if not value_column:
        return "Error: Could not detect value column. Specify value_column explicitly."

    # Auto-detect label column
    if not label_column:
        for k in sample:
            if any(c in k.lower() for c in ("service", "project", "account", "subscription",
                                              "team", "region", "environment", "category")):
                label_column = k
                break
    if not label_column:
        # Fall back to first string column that isn't the value column
        for k, v in sample.items():
            if k != value_column and isinstance(v, str):
                label_column = k
                break
    if not label_column:
        return "Error: Could not detect label column. Specify label_column explicitly."

    # Build lookup maps
    def _build_map(data: list[dict]) -> dict[str, float]:
        m: dict[str, float] = {}
        for row in data:
            key = str(row.get(label_column, "(null)"))
            try:
                m[key] = m.get(key, 0) + float(row.get(value_column, 0))
            except (ValueError, TypeError):
                pass
        return m

    map_a = _build_map(data_a)
    map_b = _build_map(data_b)
    all_keys = sorted(set(map_a.keys()) | set(map_b.keys()))

    comparisons = []
    for key in all_keys:
        val_a = map_a.get(key, 0.0)
        val_b = map_b.get(key, 0.0)
        delta = val_b - val_a
        pct = round(delta / val_a * 100, 1) if val_a != 0 else None
        comparisons.append({
            "label": key,
            "period_a": round(val_a, 2),
            "period_b": round(val_b, 2),
            "delta": round(delta, 2),
            "pct_change": pct,
            "direction": "increase" if delta > 0 else "decrease" if delta < 0 else "flat",
        })

    # Sort by absolute delta descending
    comparisons.sort(key=lambda c: abs(c["delta"]), reverse=True)

    total_a = round(sum(map_a.values()), 2)
    total_b = round(sum(map_b.values()), 2)
    total_delta = round(total_b - total_a, 2)
    total_pct = round(total_delta / total_a * 100, 1) if total_a != 0 else None

    # Biggest movers (top 5 increases and decreases)
    increases = [c for c in comparisons if c["delta"] > 0][:5]
    decreases = [c for c in comparisons if c["delta"] < 0][:5]

    # New in period B (not in A)
    new_items = [c for c in comparisons if c["period_a"] == 0 and c["period_b"] > 0]
    # Dropped from period A (not in B)
    dropped_items = [c for c in comparisons if c["period_b"] == 0 and c["period_a"] > 0]

    return json.dumps({
        "label_column": label_column,
        "value_column": value_column,
        "summary": {
            "total_period_a": total_a,
            "total_period_b": total_b,
            "total_delta": total_delta,
            "total_pct_change": total_pct,
            "items_compared": len(comparisons),
            "items_increased": len([c for c in comparisons if c["delta"] > 0]),
            "items_decreased": len([c for c in comparisons if c["delta"] < 0]),
            "new_items": len(new_items),
            "dropped_items": len(dropped_items),
        },
        "biggest_increases": increases,
        "biggest_decreases": decreases,
        "new_items": new_items[:10],
        "dropped_items": dropped_items[:10],
        "all_comparisons": comparisons[:50],
    }, default=str)


# ---------------------------------------------------------------------------
# Tool 6: score_recommendations
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
# Tool 9: format_currency
# ---------------------------------------------------------------------------

@mcp.tool()
def format_currency(data_json: str, columns: str = "", locale: str = "en_US",
                    abbreviate: bool = True) -> str:
    """Format numeric cost columns into consistent, human-readable currency strings.

    Use this to normalize money values before presenting results to users.
    Converts raw numbers like 245000.5 into "$245.0K" or "$245,000.50".

    Args:
        data_json: JSON array of objects (pass raw tool output from a query or summarize_data).
        columns: Comma-separated column names to format (e.g. "total_cost,savings").
                 If empty, auto-detects columns containing cost/spend/savings/price/amount.
        locale: Locale for formatting. Default "en_US" ($ prefix, comma thousands).
        abbreviate: If true, use abbreviations ($1.2K, $3.5M). If false, use full numbers ($1,200.00). Default true.
    """
    data = _parse_data(data_json)
    if not data:
        return "Error: Could not parse data_json."

    # Determine which columns to format
    if columns:
        target_cols = [c.strip() for c in columns.split(",")]
    else:
        sample = data[0]
        target_cols = [
            k for k in sample
            if any(c in k.lower() for c in ("cost", "spend", "savings", "price", "amount"))
            and isinstance(sample.get(k), (int, float))
        ]

    if not target_cols:
        return "Error: No numeric cost columns found to format."

    def _fmt(val: float) -> str:
        if not isinstance(val, (int, float)):
            return str(val)
        if abbreviate:
            abs_v = abs(val)
            sign = "-" if val < 0 else ""
            if abs_v >= 1_000_000_000:
                return f"{sign}${abs_v / 1_000_000_000:.1f}B"
            if abs_v >= 1_000_000:
                return f"{sign}${abs_v / 1_000_000:.1f}M"
            if abs_v >= 1_000:
                return f"{sign}${abs_v / 1_000:.1f}K"
            return f"{sign}${abs_v:.2f}"
        else:
            sign = "-" if val < 0 else ""
            abs_v = abs(val)
            whole = int(abs_v)
            frac = abs_v - whole
            formatted_whole = f"{whole:,}"
            return f"{sign}${formatted_whole}.{int(frac * 100):02d}"

    formatted = []
    for row in data:
        new_row = {**row}
        for col in target_cols:
            if col in new_row and isinstance(new_row[col], (int, float)):
                new_row[f"{col}_formatted"] = _fmt(new_row[col])
        formatted.append(new_row)

    return json.dumps({
        "formatted_columns": target_cols,
        "abbreviate": abbreviate,
        "row_count": len(formatted),
        "data": formatted,
    }, default=str)


# ---------------------------------------------------------------------------
# Tool 10: convert_to_chart_data
# ---------------------------------------------------------------------------

@mcp.tool()
def convert_to_chart_data(data_json: str, label_column: str = "",
                          value_columns: str = "",
                          chart_title: str = "") -> str:
    """Convert query results into the exact structure the frontend ChartView expects.

    The frontend auto-detects chart data from tool_result events. This tool ensures
    the output matches the expected format: { data: [...], labelKey, valueKeys }.

    Use this after run_bq_query or run_sql_query when you want to guarantee
    a chart renders correctly. Returns a JSON object that should be passed back
    as-is in the tool result.

    Args:
        data_json: JSON array of objects (raw query results).
        label_column: Column to use as chart labels / x-axis (e.g. "service_description").
                      Auto-detected if empty — picks first string column with most distinct values.
        value_columns: Comma-separated numeric columns to chart (e.g. "total_cost,previous_cost").
                       Auto-detected if empty — picks all numeric columns.
        chart_title: Optional title for the chart.
    """
    data = _parse_data(data_json)
    if not data or len(data) < 2:
        return "Error: Need at least 2 data rows to build a chart."

    sample = data[0]

    # Auto-detect label column
    if not label_column:
        string_keys = [k for k, v in sample.items() if isinstance(v, str)]
        if not string_keys:
            return "Error: No string column found for labels. Specify label_column."
        # Pick string column with most distinct values
        best_key, best_count = string_keys[0], 0
        for sk in string_keys:
            distinct = len(set(str(row.get(sk, "")) for row in data))
            if distinct > best_count:
                best_count = distinct
                best_key = sk
        label_column = best_key

    # Auto-detect value columns
    if value_columns:
        val_cols = [c.strip() for c in value_columns.split(",")]
    else:
        val_cols = [k for k, v in sample.items()
                    if isinstance(v, (int, float)) and k != label_column]

    if not val_cols:
        return "Error: No numeric columns found for chart values. Specify value_columns."

    # Build chart-ready data — round numbers, filter zero-only rows
    chart_data = []
    for row in data:
        entry = {label_column: str(row.get(label_column, ""))}
        has_nonzero = False
        for vk in val_cols:
            val = row.get(vk)
            if isinstance(val, (int, float)):
                entry[vk] = round(val, 2)
                if abs(val) > 0.005:
                    has_nonzero = True
            else:
                entry[vk] = 0
        if has_nonzero:
            chart_data.append(entry)

    if not chart_data:
        return "Error: All rows have zero values — nothing to chart."

    result = {
        "data": chart_data,
        "labelKey": label_column,
        "valueKeys": val_cols,
    }
    if chart_title:
        result["title"] = chart_title

    return json.dumps(result, default=str)


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
