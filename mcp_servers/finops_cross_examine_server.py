"""
FinOps Cross-Examine Server — MCP server for cross-cloud cost comparison.

Analyses current cloud usage patterns and computes what-if scenarios:
"If you used Service X on Cloud B instead of Cloud A, you'd save $Y/month."

Uses actual cost data from BQ tables + cloud service taxonomy for mapping.
No external pricing APIs — all data comes from the organization's own tables.

Run:
    # Dev inspector
    mcp dev mcp_servers/finops_cross_examine_server.py

    # Stdio mode (how the agent connects)
    python mcp_servers/finops_cross_examine_server.py
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
from pydantic import Field

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
logger = logging.getLogger("finops_cross_examine_server")

mcp = FastMCP("FinOps-Cross-Examine-Server")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_resource_file(relative_path: str) -> str:
    """Load a resource file from the resources/ directory."""
    path = (RESOURCES_DIR / relative_path).resolve()
    if not path.exists():
        return f"Error: Resource file not found: {relative_path}"
    return path.read_text(encoding="utf-8")


def _load_taxonomy() -> dict:
    """Load the cloud services taxonomy for cross-cloud mapping."""
    raw = _load_resource_file("analytics/cloud_services_taxonomy.json")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"mappings": []}


def _load_cross_examine_guide() -> dict:
    """Load the cross-examine benchmark data."""
    raw = _load_resource_file("analytics/cross_examine_guide.json")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_data(data_json: str) -> list[dict] | None:
    """Parse JSON string into list of dicts."""
    if not isinstance(data_json, str):
        return data_json if isinstance(data_json, list) else None
    try:
        data = json.loads(data_json)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Resources — exposed to the agent via MCP
# ---------------------------------------------------------------------------

@mcp.resource("cross-examine://guide")
def cross_examine_guide() -> str:
    """Cross-examine benchmark guide: service equivalences and pricing ratios."""
    return _load_resource_file("analytics/cross_examine_guide.json")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def map_services_across_clouds(
    services: str = Field(
        description=(
            "JSON array of service objects from current usage. "
            "Each object: {\"cloud\": \"AWS|Azure|GCP\", \"service\": \"service name\", "
            "\"monthly_cost\": 1234.56, \"usage_quantity\": 100, \"usage_unit\": \"hours\"}. "
            "Service names should match BQ table values (e.g. 'Amazon EC2', 'Compute Engine')."
        )
    ),
) -> str:
    """Map services from one cloud to equivalent services on other clouds.

    Takes the user's current service usage and returns a mapping showing
    what the equivalent service is called on each cloud, plus any known
    pricing ratio benchmarks.
    """
    data = _parse_data(services)
    if not data:
        return json.dumps({"error": "Invalid input. Provide a JSON array of service objects."})

    taxonomy = _load_taxonomy()
    guide = _load_cross_examine_guide()
    mappings = taxonomy.get("mappings", [])
    benchmarks = guide.get("benchmarks", {})

    # Build reverse lookup: cloud-specific service name → canonical + other clouds
    reverse_map: dict[str, dict] = {}
    for m in mappings:
        for cloud_key in ("aws", "azure", "gcp"):
            svc_name = m.get(cloud_key, "").lower()
            if svc_name:
                reverse_map[svc_name] = {
                    "canonical": m["canonical"],
                    "aws": m.get("aws", ""),
                    "azure": m.get("azure", ""),
                    "gcp": m.get("gcp", ""),
                }

    results = []
    for item in data:
        cloud = item.get("cloud", "").lower()
        service = item.get("service", "")
        monthly_cost = float(item.get("monthly_cost", 0))

        # Find canonical mapping
        lookup_key = service.lower()
        mapping = reverse_map.get(lookup_key)

        if not mapping:
            # Fuzzy match — check if service name contains a known mapping
            for known_name, known_mapping in reverse_map.items():
                if known_name in lookup_key or lookup_key in known_name:
                    mapping = known_mapping
                    break

        if mapping:
            canonical = mapping["canonical"]
            benchmark = benchmarks.get(canonical, {})

            alternatives = {}
            for alt_cloud in ("aws", "azure", "gcp"):
                if alt_cloud == cloud:
                    continue
                alt_service = mapping.get(alt_cloud, "")
                if alt_service:
                    ratio = benchmark.get(f"{cloud}_to_{alt_cloud}", None)
                    alt_info = {
                        "service": alt_service,
                        "cloud": alt_cloud.upper(),
                    }
                    if ratio is not None:
                        estimated_cost = round(monthly_cost * ratio, 2)
                        savings = round(monthly_cost - estimated_cost, 2)
                        savings_pct = round((1 - ratio) * 100, 1) if ratio < 1 else round((ratio - 1) * -100, 1)
                        alt_info["estimated_monthly_cost"] = estimated_cost
                        alt_info["estimated_savings"] = savings
                        alt_info["savings_percent"] = savings_pct
                        alt_info["pricing_ratio"] = ratio
                        alt_info["ratio_source"] = benchmark.get("source", "industry_benchmark")
                    else:
                        alt_info["note"] = "No benchmark ratio available. Use compare_cloud_unit_costs for actual data."
                    alternatives[alt_cloud] = alt_info

            results.append({
                "current_cloud": cloud.upper(),
                "current_service": service,
                "canonical_category": canonical,
                "monthly_cost": monthly_cost,
                "alternatives": alternatives,
            })
        else:
            results.append({
                "current_cloud": cloud.upper(),
                "current_service": service,
                "canonical_category": "unmapped",
                "monthly_cost": monthly_cost,
                "alternatives": {},
                "note": "No cross-cloud equivalent found in taxonomy. This may be a cloud-specific service.",
            })

    return json.dumps(results, indent=2)


@mcp.tool()
def compare_cloud_unit_costs(
    data_json: str = Field(
        description=(
            "JSON array of cost records from multiple clouds for the SAME service category. "
            "Each record: {\"cloud\": \"AWS|Azure|GCP\", \"service\": \"name\", "
            "\"total_cost\": 1234.56, \"total_usage\": 1000, \"usage_unit\": \"hours\", "
            "\"period\": \"2026-05\"}. "
            "Best obtained by querying each cloud's BQ table for the same service category."
        )
    ),
) -> str:
    """Compare unit costs (cost per usage unit) across clouds for the same service type.

    This uses ACTUAL cost data from the organization's BQ tables — not public pricing.
    Returns which cloud is cheapest per unit for each service category, with potential savings.
    """
    data = _parse_data(data_json)
    if not data:
        return json.dumps({"error": "Invalid input. Provide a JSON array of cost records."})

    # Group by service category (use taxonomy for normalization)
    taxonomy = _load_taxonomy()
    mappings = taxonomy.get("mappings", [])

    reverse_map: dict[str, str] = {}
    for m in mappings:
        for cloud_key in ("aws", "azure", "gcp"):
            svc_name = m.get(cloud_key, "").lower()
            if svc_name:
                reverse_map[svc_name] = m["canonical"]

    # Build per-category comparison
    categories: dict[str, list[dict]] = {}
    for record in data:
        service = record.get("service", "")
        canonical = reverse_map.get(service.lower(), service.lower().replace(" ", "_"))
        total_cost = float(record.get("total_cost", 0))
        total_usage = float(record.get("total_usage", 0))
        unit_cost = round(total_cost / total_usage, 6) if total_usage > 0 else 0

        entry = {
            "cloud": record.get("cloud", "Unknown").upper(),
            "service": service,
            "total_cost": total_cost,
            "total_usage": total_usage,
            "usage_unit": record.get("usage_unit", "units"),
            "unit_cost": unit_cost,
            "period": record.get("period", ""),
        }
        categories.setdefault(canonical, []).append(entry)

    results = []
    for canonical, entries in categories.items():
        if len(entries) < 2:
            results.append({
                "category": canonical,
                "entries": entries,
                "comparison": "Need data from at least 2 clouds to compare.",
            })
            continue

        # Sort by unit cost ascending
        sorted_entries = sorted(entries, key=lambda x: x["unit_cost"])
        cheapest = sorted_entries[0]
        most_expensive = sorted_entries[-1]

        savings_opportunities = []
        for entry in sorted_entries[1:]:
            if cheapest["unit_cost"] > 0 and entry["unit_cost"] > 0:
                potential_savings = round(
                    entry["total_cost"] * (1 - cheapest["unit_cost"] / entry["unit_cost"]), 2
                )
                savings_pct = round(
                    (1 - cheapest["unit_cost"] / entry["unit_cost"]) * 100, 1
                )
                savings_opportunities.append({
                    "switch_from": f"{entry['cloud']} ({entry['service']})",
                    "switch_to": f"{cheapest['cloud']} ({cheapest['service']})",
                    "current_monthly_cost": entry["total_cost"],
                    "estimated_new_cost": round(entry["total_cost"] - potential_savings, 2),
                    "potential_monthly_savings": potential_savings,
                    "savings_percent": savings_pct,
                })

        results.append({
            "category": canonical,
            "cheapest": {
                "cloud": cheapest["cloud"],
                "service": cheapest["service"],
                "unit_cost": cheapest["unit_cost"],
                "usage_unit": cheapest["usage_unit"],
            },
            "most_expensive": {
                "cloud": most_expensive["cloud"],
                "service": most_expensive["service"],
                "unit_cost": most_expensive["unit_cost"],
            },
            "all_entries": sorted_entries,
            "savings_opportunities": savings_opportunities,
        })

    total_potential_savings = sum(
        s["potential_monthly_savings"]
        for r in results
        for s in r.get("savings_opportunities", [])
    )

    return json.dumps({
        "comparisons": results,
        "total_potential_monthly_savings": round(total_potential_savings, 2),
        "note": "Based on actual organizational costs. Unit costs reflect negotiated rates, discounts, and RIs.",
    }, indent=2)


@mcp.tool()
def cross_examine_recommendations(
    current_usage_json: str = Field(
        description=(
            "JSON array of the user's top services with spend. "
            "Each: {\"cloud\": \"AWS|Azure|GCP\", \"service\": \"name\", "
            "\"monthly_cost\": 1234.56, \"usage_pattern\": \"steady|bursty|declining|growing\", "
            "\"commitment_type\": \"on-demand|reserved|spot|CUD|SUD\"}."
        )
    ),
    target_clouds: str = Field(
        default="all",
        description="Comma-separated clouds to consider as alternatives: 'aws,azure,gcp' or 'all'."
    ),
) -> str:
    """Generate cross-cloud migration recommendations based on usage patterns.

    Analyzes each service's usage pattern (steady, bursty, etc.) and commitment
    type to recommend whether switching clouds or pricing models could save money.
    Returns prioritized recommendations sorted by potential savings.
    """
    data = _parse_data(current_usage_json)
    if not data:
        return json.dumps({"error": "Invalid input. Provide a JSON array of service usage data."})

    taxonomy = _load_taxonomy()
    guide = _load_cross_examine_guide()
    mappings = taxonomy.get("mappings", [])
    benchmarks = guide.get("benchmarks", {})
    commitment_tips = guide.get("commitment_optimization", {})

    target_set = {"aws", "azure", "gcp"} if target_clouds == "all" else set(
        c.strip().lower() for c in target_clouds.split(",")
    )

    # Reverse map
    reverse_map: dict[str, dict] = {}
    for m in mappings:
        for cloud_key in ("aws", "azure", "gcp"):
            svc_name = m.get(cloud_key, "").lower()
            if svc_name:
                reverse_map[svc_name] = m

    recommendations = []
    for item in data:
        cloud = item.get("cloud", "").lower()
        service = item.get("service", "")
        monthly_cost = float(item.get("monthly_cost", 0))
        usage_pattern = item.get("usage_pattern", "steady").lower()
        commitment = item.get("commitment_type", "on-demand").lower()

        mapping = reverse_map.get(service.lower())
        if not mapping:
            for known_name, known_map in reverse_map.items():
                if known_name in service.lower() or service.lower() in known_name:
                    mapping = known_map
                    break

        rec = {
            "current_cloud": cloud.upper(),
            "current_service": service,
            "monthly_cost": monthly_cost,
            "usage_pattern": usage_pattern,
            "commitment_type": commitment,
            "recommendations": [],
        }

        # 1) Cross-cloud alternatives
        if mapping:
            canonical = mapping["canonical"]
            bm = benchmarks.get(canonical, {})

            for alt_cloud in target_set:
                if alt_cloud == cloud:
                    continue
                alt_service = mapping.get(alt_cloud, "")
                if not alt_service:
                    continue

                ratio = bm.get(f"{cloud}_to_{alt_cloud}")
                r = {
                    "type": "cross_cloud_switch",
                    "target_cloud": alt_cloud.upper(),
                    "target_service": alt_service,
                    "canonical_category": canonical,
                }

                if ratio is not None:
                    est_cost = round(monthly_cost * ratio, 2)
                    savings = round(monthly_cost - est_cost, 2)
                    r["estimated_monthly_cost"] = est_cost
                    r["estimated_monthly_savings"] = savings
                    r["savings_percent"] = round((1 - ratio) * 100, 1)
                    r["confidence"] = "medium" if abs(ratio - 1.0) > 0.15 else "low"
                else:
                    r["note"] = "Use compare_cloud_unit_costs with actual BQ data for precise comparison."
                    r["confidence"] = "requires_data"

                # Pattern-based advice
                if usage_pattern == "bursty":
                    r["pattern_advice"] = (
                        f"Bursty workloads favor serverless or spot instances. "
                        f"Consider {alt_cloud.upper()}'s serverless/spot options for {alt_service}."
                    )
                elif usage_pattern == "steady" and commitment == "on-demand":
                    r["pattern_advice"] = (
                        f"Steady on-demand workloads can save 30-60% with reservations/commitments. "
                        f"Consider reserved pricing on any cloud before switching."
                    )
                elif usage_pattern == "declining":
                    r["pattern_advice"] = (
                        "Declining usage suggests this workload may be decommissioned. "
                        "Consider staying on current cloud but right-sizing or consolidating."
                    )

                rec["recommendations"].append(r)

        # 2) Commitment optimization (same cloud)
        if commitment == "on-demand" and usage_pattern in ("steady", "growing"):
            commit_tip = commitment_tips.get(cloud, {})
            if commit_tip:
                rec["recommendations"].append({
                    "type": "commitment_optimization",
                    "target_cloud": cloud.upper(),
                    "target_service": service,
                    "action": commit_tip.get("action", "Consider reserved/committed pricing"),
                    "typical_savings_percent": commit_tip.get("typical_savings_pct", "30-60%"),
                    "note": "Steady/growing on-demand workloads almost always benefit from commitments.",
                    "confidence": "high",
                })

        # Sort recommendations by savings (highest first)
        rec["recommendations"].sort(
            key=lambda x: x.get("estimated_monthly_savings", 0), reverse=True
        )
        recommendations.append(rec)

    # Sort all items by monthly cost descending (biggest spend first)
    recommendations.sort(key=lambda x: x["monthly_cost"], reverse=True)

    total_potential = sum(
        r.get("estimated_monthly_savings", 0)
        for item in recommendations
        for r in item.get("recommendations", [])
        if r.get("type") == "cross_cloud_switch"
    )

    return json.dumps({
        "cross_examine_results": recommendations,
        "total_potential_monthly_savings_cross_cloud": round(total_potential, 2),
        "methodology": (
            "Estimates based on organizational benchmark ratios and usage patterns. "
            "For precise savings, use compare_cloud_unit_costs with actual BQ cost data. "
            "Commitment optimization savings are typical industry ranges."
        ),
    }, indent=2)


@mcp.tool()
def generate_what_if_scenario(
    scenario_json: str = Field(
        description=(
            "JSON object defining the what-if scenario. Format: "
            "{\"services\": [{\"cloud\": \"AWS\", \"service\": \"Amazon EC2\", "
            "\"monthly_cost\": 5000, \"action\": \"switch_to_gcp|switch_to_azure|switch_to_aws|"
            "commit_reserved|switch_to_spot|rightsize_50pct\"}], "
            "\"time_horizon_months\": 12}. "
            "The action field specifies what change to model."
        )
    ),
) -> str:
    """Generate a what-if cost projection for hypothetical changes.

    Models scenarios like: "What if we moved EC2 to GCP Compute Engine?"
    or "What if we committed to reserved instances on all steady workloads?"
    Returns monthly projections and total savings over the time horizon.
    """
    try:
        scenario = json.loads(scenario_json) if isinstance(scenario_json, str) else scenario_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid scenario JSON."})

    services = scenario.get("services", [])
    horizon = int(scenario.get("time_horizon_months", 12))

    if not services:
        return json.dumps({"error": "No services provided in scenario."})

    taxonomy = _load_taxonomy()
    guide = _load_cross_examine_guide()
    mappings = taxonomy.get("mappings", [])
    benchmarks = guide.get("benchmarks", {})

    reverse_map: dict[str, dict] = {}
    for m in mappings:
        for cloud_key in ("aws", "azure", "gcp"):
            svc_name = m.get(cloud_key, "").lower()
            if svc_name:
                reverse_map[svc_name] = {"canonical": m["canonical"], **m}

    # Action multipliers
    action_multipliers = {
        "commit_reserved": 0.55,     # ~45% savings typical for 1-yr RI
        "switch_to_spot": 0.35,      # ~65% savings typical for spot
        "rightsize_50pct": 0.50,     # 50% reduction
    }

    projections = []
    total_current_annual = 0
    total_projected_annual = 0

    for svc in services:
        cloud = svc.get("cloud", "").lower()
        service = svc.get("service", "")
        monthly_cost = float(svc.get("monthly_cost", 0))
        action = svc.get("action", "")

        current_total = monthly_cost * horizon
        total_current_annual += current_total

        proj = {
            "service": service,
            "cloud": cloud.upper(),
            "action": action,
            "current_monthly": monthly_cost,
            "current_total": round(current_total, 2),
        }

        if action.startswith("switch_to_"):
            target_cloud = action.replace("switch_to_", "").lower()
            mapping = reverse_map.get(service.lower())

            if mapping:
                canonical = mapping["canonical"]
                ratio = benchmarks.get(canonical, {}).get(f"{cloud}_to_{target_cloud}")
                target_service = mapping.get(target_cloud, f"Equivalent on {target_cloud.upper()}")

                if ratio:
                    new_monthly = round(monthly_cost * ratio, 2)
                else:
                    # Default estimate: assume ~10% variance if no benchmark
                    new_monthly = monthly_cost
                    proj["note"] = "No benchmark data — showing same cost. Query actual data for precision."

                new_total = round(new_monthly * horizon, 2)
                savings_total = round(current_total - new_total, 2)

                proj["target_cloud"] = target_cloud.upper()
                proj["target_service"] = target_service
                proj["projected_monthly"] = new_monthly
                proj["projected_total"] = new_total
                proj["savings_total"] = savings_total
                proj["savings_monthly"] = round(monthly_cost - new_monthly, 2)
                total_projected_annual += new_total
            else:
                proj["projected_monthly"] = monthly_cost
                proj["projected_total"] = current_total
                proj["savings_total"] = 0
                proj["note"] = "Service not found in taxonomy. Cannot estimate cross-cloud cost."
                total_projected_annual += current_total

        elif action in action_multipliers:
            multiplier = action_multipliers[action]
            new_monthly = round(monthly_cost * multiplier, 2)
            new_total = round(new_monthly * horizon, 2)
            proj["projected_monthly"] = new_monthly
            proj["projected_total"] = new_total
            proj["savings_total"] = round(current_total - new_total, 2)
            proj["savings_monthly"] = round(monthly_cost - new_monthly, 2)
            total_projected_annual += new_total
        else:
            proj["projected_monthly"] = monthly_cost
            proj["projected_total"] = current_total
            proj["savings_total"] = 0
            proj["note"] = f"Unknown action '{action}'. Supported: switch_to_aws, switch_to_azure, switch_to_gcp, commit_reserved, switch_to_spot, rightsize_50pct."
            total_projected_annual += current_total

        projections.append(proj)

    # Build monthly timeline for charting
    monthly_timeline = []
    for month in range(1, horizon + 1):
        current_m = sum(p["current_monthly"] for p in projections)
        projected_m = sum(p.get("projected_monthly", p["current_monthly"]) for p in projections)
        monthly_timeline.append({
            "month": month,
            "current_cost": round(current_m, 2),
            "projected_cost": round(projected_m, 2),
            "cumulative_savings": round((current_m - projected_m) * month, 2),
        })

    return json.dumps({
        "scenario_summary": {
            "time_horizon_months": horizon,
            "total_current_cost": round(total_current_annual, 2),
            "total_projected_cost": round(total_projected_annual, 2),
            "total_savings": round(total_current_annual - total_projected_annual, 2),
            "savings_percent": round(
                (1 - total_projected_annual / total_current_annual) * 100, 1
            ) if total_current_annual > 0 else 0,
        },
        "service_projections": projections,
        "monthly_timeline": monthly_timeline,
        "chart_data": {
            "type": "line",
            "title": "What-If Cost Projection",
            "x_axis": "Month",
            "y_axis": "Cost (USD)",
            "series": [
                {"name": "Current Cost", "data": [t["current_cost"] for t in monthly_timeline]},
                {"name": "Projected Cost", "data": [t["projected_cost"] for t in monthly_timeline]},
            ],
        },
        "disclaimer": (
            "Projections based on benchmark ratios and industry averages. "
            "Actual costs depend on negotiated rates, usage patterns, data transfer, "
            "and migration costs (not included). Validate with actual BQ pricing data."
        ),
    }, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
