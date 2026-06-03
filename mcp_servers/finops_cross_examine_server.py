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
import re
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


# BQ uses full AWS service names; taxonomy uses short names.
# This map normalises the most common mismatches.
_BQ_SERVICE_ALIASES: dict[str, str] = {
    "amazon elastic compute cloud": "amazon ec2",
    "amazon relational database service": "amazon rds",
    "amazon simple storage service": "amazon s3",
    "amazon simple notification service": "amazon sns",
    "amazon simple queue service": "amazon sqs",
    "amazon simple email service": "amazon ses",
    "elastic load balancing": "elastic load balancing",
    "aws data transfer": "aws data transfer",
    "savings plans for aws compute usage": "amazon ec2",  # savings plans are EC2-adjacent
    "amazon elastic block store": "amazon ebs",
    "amazon elastic file system": "amazon efs",
    "amazon elastic container service": "amazon ecs",
    "amazon elastic kubernetes service": "amazon eks",
}


def _normalise_service_name(name: str) -> str:
    """Normalise a BQ service name to its taxonomy-friendly short form."""
    return _BQ_SERVICE_ALIASES.get(name.lower(), name.lower())


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


_instance_map_cache: dict | None = None


def _load_instance_map() -> dict:
    """Load the compute instance mapping (Azure→AWS→GCP) with caching."""
    global _instance_map_cache
    if _instance_map_cache is not None:
        return _instance_map_cache
    raw = _load_resource_file("analytics/compute_instance_mapping.json")
    try:
        _instance_map_cache = json.loads(raw)
        return _instance_map_cache
    except (json.JSONDecodeError, TypeError):
        return {"mappings": []}


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
# Compute family classification
# ---------------------------------------------------------------------------

# Maps Azure VM family prefixes to compute_vm sub-categories in the guide.
# Order matters — longer prefixes first for correct matching.
_AZURE_FAMILY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^N[CDV]", re.IGNORECASE), "compute_vm_gpu"),
    (re.compile(r"^F", re.IGNORECASE), "compute_vm_compute_optimized"),
    (re.compile(r"^E", re.IGNORECASE), "compute_vm_memory_optimized"),
    (re.compile(r"^L", re.IGNORECASE), "compute_vm_storage_optimized"),
    (re.compile(r"^B", re.IGNORECASE), "compute_vm_burstable"),
    (re.compile(r"^[DMA]", re.IGNORECASE), "compute_vm_general_purpose"),
]


def _classify_azure_vm_family(series_or_size: str) -> str:
    """Return the benchmark key for an Azure VM series/size.

    Examples:
        'Dsv4 Series' → 'compute_vm_general_purpose'
        'FSv2 Series' → 'compute_vm_compute_optimized'
        'Edsv5 Series' → 'compute_vm_memory_optimized'
        'D16s v4'      → 'compute_vm_general_purpose'

    Falls back to generic 'compute_vm' if no match.
    """
    # Strip " Series" suffix and any leading "Virtual Machines" prefix
    clean = re.sub(r"\s*Series\s*$", "", series_or_size, flags=re.IGNORECASE).strip()
    clean = re.sub(r"^Virtual\s+Machines?\s+", "", clean, flags=re.IGNORECASE).strip()

    # For compound names like "Dv3/DSv3", use first part
    if "/" in clean:
        clean = clean.split("/")[0].strip()

    # Strip digits from middle of VM sizes like "D16s" → "D"
    # But keep leading letters intact
    lead = re.match(r"^([A-Za-z]+)", clean)
    if not lead:
        return "compute_vm"

    prefix = lead.group(1)
    for pattern, category in _AZURE_FAMILY_RULES:
        if pattern.match(prefix):
            return category

    return "compute_vm"


def _get_instance_equivalents(series_name: str) -> list[dict]:
    """Look up instance mappings for a series name. Returns list of {azure, aws, gcp, vcpus, memory}."""
    mapping_data = _load_instance_map()
    all_mappings = mapping_data.get("mappings", [])

    clean = re.sub(r"\s*Series\s*$", "", series_name, flags=re.IGNORECASE).strip()
    if not clean:
        return []

    parts = clean.split("/")
    pats: list[str] = []
    for part in parts:
        part = part.strip()
        m = re.match(r"^([A-Za-z]{1,2}?)([a-zA-Z]*?)(v\d+)$", part)
        if not m:
            continue
        family, suffix, ver = m.group(1), m.group(2), m.group(3)
        pats.append(rf"{re.escape(family)}\d+{re.escape(suffix)}\s*{re.escape(ver)}")

    if not pats:
        return []

    combined = "|".join(pats)
    pat = re.compile(rf"^({combined})$", re.IGNORECASE)
    return [m for m in all_mappings if pat.match(m["azure_vm_size"])]


# ---------------------------------------------------------------------------
# Resources — exposed to the agent via MCP
# ---------------------------------------------------------------------------

@mcp.resource("cross-examine://guide")
def cross_examine_guide() -> str:
    """Cross-examine benchmark guide: service equivalences and pricing ratios."""
    return _load_resource_file("analytics/cross_examine_guide.json")


@mcp.resource("cross-examine://compute-instance-mapping")
def compute_instance_mapping_resource() -> str:
    """Compute instance type mapping: Azure VM sizes → AWS instances → GCP instances (1293 entries)."""
    return _load_resource_file("analytics/compute_instance_mapping.json")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def map_compute_instances(
    instance_names: str = Field(
        description=(
            "JSON array of instance names to map, e.g. "
            '[{"cloud": "azure", "instance": "D4s v3"}, {"cloud": "aws", "instance": "m5.xlarge"}]. '
            "cloud must be one of: azure, aws, gcp. "
            "For Azure you can also pass a series name like 'Dsv4 Series' or "
            "'Dv3/DSv3 Series' and the tool returns all VM sizes in that series. "
            "Raw meter_sub_category values from BQ are accepted directly."
        )
    ),
) -> str:
    """Map specific compute VM/instance types across clouds.

    Given one or more VM sizes from any cloud, returns the equivalent
    instance types on the other clouds with vCPU and memory specs.
    Use this for instance-level cross-examination of compute costs.

    Accepts:
    - Specific VM sizes: "D4s v3", "m5.xlarge", "n2-standard-4"
    - Azure series names: "Dsv4 Series", "Dv3/DSv3 Series", "FSv2 Series"
    - Raw Azure meter names: "Virtual Machines Dsv4 Series - D16s v4 - US East"
    """
    data = _parse_data(instance_names)
    if not data:
        return json.dumps({"error": "Invalid input. Provide a JSON array of instance objects."})

    mapping_data = _load_instance_map()
    all_mappings = mapping_data.get("mappings", [])

    def _norm(s: str) -> str:
        """Lowercase + collapse all whitespace/underscores for matching."""
        return re.sub(r"[\s_]+", "", s.lower())

    def _azure_series_to_pattern(name: str) -> re.Pattern | None:
        """Convert an Azure series name like 'Dsv4' into a regex that matches
        individual VM sizes like 'D4s v4', 'D16s v4', etc.

        Series naming: FamilySuffixVersion  (e.g. Dsv4 → D + s + v4)
        VM size naming: Family{N}Suffix vVersion (e.g. D4s v4)
        """
        clean = re.sub(r"\s*Series\s*$", "", name, flags=re.IGNORECASE).strip()
        if not clean:
            return None
        parts = clean.split("/")
        pats: list[str] = []
        for part in parts:
            part = part.strip()
            m = re.match(r"^([A-Za-z]{1,2}?)([a-zA-Z]*?)(v\d+)$", part)
            if not m:
                continue
            family = m.group(1)    # e.g. "D", "F", "E", "DC"
            suffix = m.group(2)    # e.g. "s", "ds", "as", "S", ""
            ver = m.group(3)       # e.g. "v4", "v3"
            # Pattern: family + digits + suffix + optional space + version
            pats.append(
                rf"{re.escape(family)}\d+{re.escape(suffix)}\s*{re.escape(ver)}"
            )
        if not pats:
            return None
        return re.compile(rf"^({'|'.join(pats)})$", re.IGNORECASE)

    # Build lookup indices with normalized keys
    azure_idx: dict[str, dict] = {}
    aws_idx: dict[str, list[dict]] = {}
    gcp_idx: dict[str, list[dict]] = {}
    for m in all_mappings:
        azure_idx[_norm(m["azure_vm_size"])] = m
        aws_idx.setdefault(_norm(m["aws_instance"]), []).append(m)
        gcp_idx.setdefault(_norm(m["gcp_instance"]), []).append(m)

    # Regex to extract VM size from Azure meter names like
    # "Virtual Machines Dsv4 Series - D16s v4 - US East"
    _AZURE_METER_RE = re.compile(
        r"Virtual\s+Machines?\s+\S+\s+Series\s*-\s*(.+?)\s*-\s*\S",
        re.IGNORECASE,
    )
    # Detect series-only names like "Dsv4 Series", "Dv3/DSv3 Series"
    _AZURE_SERIES_RE = re.compile(
        r"^[\w/]+\s+Series$|^[A-Z]{1,2}[a-z]*v\d+$|^[\w/]+v\d+\s+Series$",
        re.IGNORECASE,
    )

    results = []
    for item in data:
        cloud = item.get("cloud", "").lower()
        instance = item.get("instance", "").strip()

        # Try to extract VM size from Azure meter name format
        if cloud == "azure":
            meter_match = _AZURE_METER_RE.search(instance)
            if meter_match:
                instance = meter_match.group(1).strip()

        lookup = _norm(instance)

        matches = []
        if cloud == "azure":
            # 1. Exact match
            hit = azure_idx.get(lookup)
            if hit:
                matches = [hit]
            else:
                # 2. Series-level match: "Dsv4 Series" → all D{N}s v4 VMs
                series_pat = _azure_series_to_pattern(instance)
                if series_pat:
                    matches = [
                        m for m in all_mappings
                        if series_pat.match(m["azure_vm_size"])
                    ]
                # 3. Fallback partial substring match
                if not matches:
                    matches = [
                        m for k, m in azure_idx.items()
                        if lookup in k or k in lookup
                    ]
        elif cloud == "aws":
            matches = aws_idx.get(lookup, [])
            if not matches:
                matches = [m for entries in aws_idx.values() for m in entries
                           if lookup in _norm(m["aws_instance"])]
        elif cloud == "gcp":
            matches = gcp_idx.get(lookup, [])
            if not matches:
                matches = [m for entries in gcp_idx.values() for m in entries
                           if lookup in _norm(m["gcp_instance"])]

        if matches:
            results.append({
                "query": {"cloud": cloud, "instance": instance},
                "match_type": "series" if len(matches) > 1 else "exact",
                "matches": [
                    {
                        "azure_vm_size": m["azure_vm_size"],
                        "aws_instance": m["aws_instance"],
                        "gcp_instance": m["gcp_instance"],
                        "vcpus": m["vcpus"],
                        "memory": m["memory"],
                    }
                    for m in matches[:15]  # Cap at 15 for series
                ],
            })
        else:
            results.append({
                "query": {"cloud": cloud, "instance": instance},
                "matches": [],
                "note": f"No mapping found for {instance} on {cloud}",
            })

    return json.dumps({"results": results, "total_mappings_available": len(all_mappings)}, indent=2)

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
        lookup_key = _normalise_service_name(service)
        mapping = reverse_map.get(lookup_key)
        if not mapping:
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

        # Detect if this is an Azure VM series (e.g. "Dsv4 Series", "FSv2 Series")
        is_vm_series = bool(re.search(r"(?:Series|v\d+)$", service.strip(), re.IGNORECASE))

        mapping = reverse_map.get(service.lower())
        if not mapping:
            mapping = reverse_map.get(_normalise_service_name(service))
        if not mapping:
            for known_name, known_map in reverse_map.items():
                if known_name in service.lower() or service.lower() in known_name:
                    mapping = known_map
                    break
            # If still no mapping but it's a VM series, treat as compute_vm
            if not mapping and is_vm_series:
                mapping = {"canonical": "compute_vm", "aws": "Amazon EC2", "azure": "Virtual Machines", "gcp": "Compute Engine"}

        rec = {
            "current_cloud": cloud.upper(),
            "current_service": service,
            "monthly_cost": monthly_cost,
            "usage_pattern": usage_pattern,
            "commitment_type": commitment,
            "recommendations": [],
        }

        # For VM series, use family-specific benchmark instead of generic compute_vm
        if is_vm_series and cloud == "azure":
            family_key = _classify_azure_vm_family(service)
        else:
            family_key = None

        # 1) Cross-cloud alternatives
        if mapping:
            canonical = mapping["canonical"]

            # Use family-specific benchmark if available, else fall back to canonical
            if family_key:
                bm = benchmarks.get(family_key, benchmarks.get(canonical, {}))
                effective_category = family_key
            else:
                bm = benchmarks.get(canonical, {})
                effective_category = canonical

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
                    "benchmark_category": effective_category,
                }

                if ratio is not None:
                    est_cost = round(monthly_cost * ratio, 2)
                    savings = round(monthly_cost - est_cost, 2)
                    r["estimated_monthly_cost"] = est_cost
                    r["estimated_monthly_savings"] = savings
                    r["savings_percent"] = round((1 - ratio) * 100, 1)
                    r["pricing_ratio"] = ratio
                    r["confidence"] = "medium" if abs(ratio - 1.0) > 0.15 else "low"
                    r["ratio_source"] = bm.get("source", "industry_benchmark")
                else:
                    r["note"] = "Use compare_cloud_unit_costs with actual BQ data for precise comparison."
                    r["confidence"] = "requires_data"

                # Enrich VM series with instance-level mappings
                if is_vm_series and cloud == "azure":
                    equivalents = _get_instance_equivalents(service)
                    if equivalents:
                        cloud_key = {"aws": "aws_instance", "gcp": "gcp_instance"}.get(alt_cloud)
                        if cloud_key:
                            r["instance_equivalents"] = [
                                {
                                    "azure": eq["azure_vm_size"],
                                    alt_cloud: eq[cloud_key],
                                    "vcpus": eq["vcpus"],
                                    "memory": eq["memory"],
                                }
                                for eq in equivalents[:8]
                            ]

                # Pattern-based advice
                if usage_pattern == "bursty":
                    r["pattern_advice"] = (
                        f"Bursty workloads favor serverless or spot instances. "
                        f"Consider {alt_cloud.upper()}'s serverless/spot options for {alt_service}."
                    )
                elif usage_pattern == "steady" and commitment == "on-demand":
                    r["pattern_advice"] = (
                        f"Steady on-demand workloads can save 30-60% with reservations/commitments. "
                        f"Consider reserved pricing on either cloud before or after switching."
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

        # Sort: cross-cloud with savings first, then commitment optimization
        rec["recommendations"].sort(
            key=lambda x: (
                0 if x.get("type") == "cross_cloud_switch" else 1,
                -(x.get("estimated_monthly_savings", 0)),
            )
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

    def _lookup_service(service_name: str) -> dict | None:
        """Look up service in reverse_map with alias + fuzzy fallback."""
        key = _normalise_service_name(service_name)
        hit = reverse_map.get(key)
        if hit:
            return hit
        # fuzzy: check substring containment
        for known, known_map in reverse_map.items():
            if known in key or key in known:
                return known_map
        return None

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
            mapping = _lookup_service(service)

            # Detect VM series and use family-specific benchmark
            is_vm_series = bool(re.search(r"(?:Series|v\d+)$", service.strip(), re.IGNORECASE))
            if not mapping and is_vm_series:
                mapping = {"canonical": "compute_vm", "aws": "Amazon EC2", "azure": "Virtual Machines", "gcp": "Compute Engine"}

            if mapping:
                canonical = mapping["canonical"]

                # Family-specific ratio for VM series (e.g. compute_vm_compute_optimized)
                if is_vm_series and cloud == "azure":
                    family_key = _classify_azure_vm_family(service)
                    bm = benchmarks.get(family_key, benchmarks.get(canonical, {}))
                else:
                    bm = benchmarks.get(canonical, {})

                ratio = bm.get(f"{cloud}_to_{target_cloud}")
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
                if ratio:
                    proj["pricing_ratio"] = ratio
                    proj["ratio_source"] = bm.get("source", "industry_benchmark")

                # Include instance equivalents for VM series
                if is_vm_series:
                    equivalents = _get_instance_equivalents(service)
                    if equivalents:
                        cloud_key = {"aws": "aws_instance", "gcp": "gcp_instance"}.get(target_cloud)
                        if cloud_key:
                            proj["instance_equivalents"] = [
                                {"azure": eq["azure_vm_size"], target_cloud: eq[cloud_key],
                                 "vcpus": eq["vcpus"], "memory": eq["memory"]}
                                for eq in equivalents[:8]
                            ]

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
# Rightsizing rules cache
# ---------------------------------------------------------------------------

_rightsizing_cache: dict | None = None


def _load_rightsizing_rules() -> dict:
    """Load the VM rightsizing rules."""
    global _rightsizing_cache
    if _rightsizing_cache is not None:
        return _rightsizing_cache
    raw = _load_resource_file("analytics/vm_rightsizing_rules.json")
    try:
        _rightsizing_cache = json.loads(raw)
        return _rightsizing_cache
    except (json.JSONDecodeError, TypeError):
        return {"rules": {}, "families": {}}


def _detect_family(series_name: str) -> str | None:
    """Detect VM family from a series/resource name."""
    rules = _load_rightsizing_rules()
    families = rules.get("families", {})
    upper = series_name.upper().strip()
    for fam_key, fam_data in families.items():
        for s in fam_data.get("series", []):
            s_up = s.upper()
            if s_up in upper:
                return fam_key
            # Extract prefix (e.g. "D-Series" → "D", "Dsv4" stays "DSV4")
            prefix = re.sub(r'[-\s]?SERIES$', '', s_up).strip()
            if prefix and upper.startswith(prefix):
                return fam_key
    # Fallback: use the regex classifier
    return _classify_azure_vm_family(series_name).replace("compute_vm_", "") or None


def _parse_condition(condition: str) -> tuple[str, float, float | None]:
    """Parse a condition string like '< 20', '> 85', '5-20', '30-60'.
    Returns (operator, value1, value2).
    operator: 'lt', 'gt', 'range'
    """
    condition = condition.strip()
    if "-" in condition and not condition.startswith("<") and not condition.startswith(">"):
        parts = condition.split("-")
        return ("range", float(parts[0].strip()), float(parts[1].strip()))
    elif condition.startswith("< ") or condition.startswith("<"):
        return ("lt", float(condition.lstrip("< ")), None)
    elif condition.startswith("> ") or condition.startswith(">"):
        return ("gt", float(condition.lstrip("> ")), None)
    else:
        return ("unknown", 0, None)


def _check_condition(op: str, v1: float, v2: float | None, actual: float) -> bool:
    """Check if actual value matches the condition."""
    if op == "lt":
        return actual < v1
    elif op == "gt":
        return actual > v1
    elif op == "range":
        return v1 <= actual <= v2
    return False


@mcp.resource("cross-examine://rightsizing-rules")
def rightsizing_rules_resource() -> str:
    """VM rightsizing rules: utilization thresholds and recommendations for each VM family."""
    return _load_resource_file("analytics/vm_rightsizing_rules.json")


@mcp.tool()
def evaluate_vm_rightsizing(
    vm_metrics_json: str = Field(
        description=(
            "JSON array of VM utilization data. Each entry: "
            '{"resource_name": "vm-prod-01", "series": "D-Series", '
            '"metric_name": "Percent CPU", "metric_value": 12.5, '
            '"monthly_cost": 450.00}. '
            "series should match Azure VM family naming. "
            "metric_name: 'Percent CPU', 'Memory %', 'Max Memory', 'Disk IOPS'. "
            "metric_value: the utilization value (0-100 for percentages)."
        )
    ),
    method: str = Field(
        default="p95_30day",
        description="Which rule set to apply: 'point_in_time' (current snapshot) or 'p95_30day' (30-day P95, safer for bursty workloads)."
    ),
) -> str:
    """Evaluate VMs against proprietary rightsizing rules based on utilization metrics.

    Takes VM utilization data (CPU%, Memory%, IOPS) and returns actionable
    recommendations: delete idle VMs, downsize oversized ones, cross-family
    moves (e.g., F-Series with low CPU → D-Series), and upsize warnings.

    Two methods available:
    - point_in_time: Current utilization snapshot. Fast but may miss bursty workloads.
    - p95_30day: 95th percentile over 30 days. Safer — avoids deleting machines
      that run heavy jobs periodically.

    Use after querying azure_utilization table for metric data.
    """
    data = _parse_data(vm_metrics_json)
    if not data:
        return json.dumps({"error": "Invalid input. Provide a JSON array of VM metric data."})

    rules_data = _load_rightsizing_rules()
    rule_set = rules_data.get("rules", {}).get(method, [])
    families = rules_data.get("families", {})
    strategies = rules_data.get("additional_strategies", [])

    if not rule_set:
        return json.dumps({"error": f"Unknown method '{method}'. Use 'point_in_time' or 'p95_30day'."})

    results = []
    total_potential_savings = 0

    # Metric name aliases: BQ data may use different names than our rules
    _METRIC_ALIASES = {
        "available memory percentage": ("memory %", True),  # (canonical_name, invert_value)
        "percentage cpu": ("Percent CPU", False),  # BQ uses 'Percentage CPU', rules use 'Percent CPU'
    }

    for vm in data:
        resource = vm.get("resource_name", "unknown")
        series = vm.get("series", "")
        metric_name = vm.get("metric_name", "")
        metric_value = float(vm.get("metric_value", 0))
        monthly_cost = float(vm.get("monthly_cost", 0))

        # Auto-convert known metric aliases (e.g. Available Memory % → Memory %)
        alias = _METRIC_ALIASES.get(metric_name.lower())
        if alias:
            metric_name, invert = alias
            if invert:
                metric_value = 100.0 - metric_value

        family = _detect_family(series)

        # Find all matching rules for this VM
        matching_rules = []
        for rule in rule_set:
            rule_family = rule.get("family", "")
            rule_metric = rule.get("metric", "").lower()

            # Check family match
            if rule_family != family:
                continue

            # Check metric match
            if rule_metric not in metric_name.lower():
                continue

            # Check condition
            cond = rule.get("condition", "")
            if cond in ("high_latency_spikes",):
                continue  # Can't evaluate qualitative conditions from numeric data

            op, v1, v2 = _parse_condition(cond)
            if op == "unknown":
                continue

            if _check_condition(op, v1, v2, metric_value):
                # Skip if we already have a higher-severity match for the same metric
                # (avoids double-counting overlapping ranges like <2 and <20)
                if any(m["_rule_metric"] == rule_metric for m in matching_rules):
                    continue

                savings_pct = rule.get("estimated_savings_pct", 0)
                est_savings = round(monthly_cost * savings_pct / 100, 2) if savings_pct > 0 else 0
                total_potential_savings += est_savings

                match = {
                    "rule_severity": rule["severity"],
                    "action": rule["action"],
                    "recommendation": rule["recommendation"],
                }
                if rule.get("target_family"):
                    target_fam = families.get(rule["target_family"], {})
                    match["target_family"] = rule["target_family"]
                    match["target_azure_series"] = target_fam.get("series", [])[:3]
                    match["target_aws_equivalent"] = target_fam.get("aws_equivalent", "")
                    match["target_gcp_equivalent"] = target_fam.get("gcp_equivalent", "")
                if savings_pct:
                    match["estimated_savings_pct"] = savings_pct
                    match["estimated_monthly_savings"] = est_savings
                match["_rule_metric"] = rule_metric  # track for dedup

                matching_rules.append(match)

        if matching_rules:
            # Sort by severity: critical > high > warning > medium > info
            severity_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "info": 4}
            matching_rules.sort(key=lambda r: severity_order.get(r["rule_severity"], 5))
            for m in matching_rules:
                m.pop("_rule_metric", None)  # remove internal tracking key

            results.append({
                "resource_name": resource,
                "series": series,
                "family": family,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "monthly_cost": monthly_cost,
                "findings": matching_rules,
            })
        else:
            results.append({
                "resource_name": resource,
                "series": series,
                "family": family,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "monthly_cost": monthly_cost,
                "findings": [{"rule_severity": "info", "action": "optimized", "recommendation": "No rightsizing issues detected. VM appears well-sized for its workload."}],
            })

    # Sort results: critical findings first, then by monthly cost
    severity_priority = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "info": 4}
    results.sort(key=lambda r: (
        severity_priority.get(r["findings"][0]["rule_severity"], 5),
        -r["monthly_cost"],
    ))

    return json.dumps({
        "method": method,
        "method_label": rules_data.get("methods", {}).get(method, {}).get("label", method),
        "total_vms_evaluated": len(data),
        "vms_with_findings": sum(1 for r in results if r["findings"][0]["action"] != "optimized"),
        "total_potential_monthly_savings": round(total_potential_savings, 2),
        "results": results,
        "additional_strategies": strategies,
        "note": (
            "These are proprietary rightsizing recommendations based on utilization thresholds. "
            "Always validate with application owners before acting — some VMs may have "
            "specific performance requirements or periodic batch jobs."
        ),
    }, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
