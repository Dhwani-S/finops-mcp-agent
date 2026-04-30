"""
FinOps File Server — MCP server for report CRUD operations.

All file operations are sandboxed to the reports/ directory.

Run:
    # Dev inspector (test tools/resources/prompts in browser)
    mcp dev mcp_servers/finops_file_server.py

    # Stdio mode (how the agent connects)
    python mcp_servers/finops_file_server.py
"""

from __future__ import annotations

import csv 
import io
import json 
import os 
from pathlib import Path 

from mcp.server.fastmcp import FastMCP 

mcp = FastMCP("FinOps-File-Server")

SANDBOX = Path(__file__).parent.parent/"reports"
SANDBOX.mkdir(exist_ok=True)

def _safe_path(relative: str) -> Path:
    """Resolve a relative path inside SANDBOX. Reject anything that escapes."""
    p = (SANDBOX / relative).resolve()
    if SANDBOX.resolve() not in p.parents and p != SANDBOX.resolve():
        raise ValueError(f"Path '{relative}' is outside the sandbox")
    return p 

# Tool implementations
@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Save or overwrite a file in the reports sandbox. Atomic write (temp + rename)."""
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(str(temp), str(target))
    return f"Written: {path} ({len(content)} chars)"

@mcp.tool()
def append_file(path: str, content: str) -> str:
    """Append content to an existing file in the reports sandbox."""
    target = _safe_path(path)
    if not target.exists():
        return f"Error: {path} does not exist. Use write_file to create it first."
    with open(target, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended: {path} ({len(content)} chars)"

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file from the reports sandbox."""
    target = _safe_path(path)
    if not target.exists():
        return f"Error: {path} does not exist."
    return target.read_text(encoding="utf-8")

@mcp.tool()
def list_files(subdir: str = "") -> str:
    """List files in the reports sandbox, optionally within a subdirectory."""
    target = _safe_path(subdir) if subdir else SANDBOX
    if not target.is_dir():
        return f"Error: {subdir} is not a valid directory."
    entries = []
    for item in sorted(target.iterdir()):
        rel = item.relative_to(SANDBOX)
        suffix = "/" if item.is_dir() else ""
        entries.append(f"{rel}{suffix}")
    return "\n".join(entries) if entries else "(empty)"

@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file from the reports sandbox. Cannot delete directories."""
    target = _safe_path(path)
    if not target.exists():
        return f"Error: {path} not found."
    if target.is_dir():
        return "Error: Cannot delete directories. Only files."
    target.unlink()
    return f"Deleted: {path}"

@mcp.tool()
def export_csv(filename: str, json_data: str) -> str:
    """Convert JSON array of objects to CSV and save in the reports sandbox.
    
    Args:
        filename: Output filename (e.g., 'costs_april.csv')
        json_data: JSON string of array of objects, e.g. '[{"service":"EC2","cost":1234}]'
    """
    try:
        rows = json.loads(json_data)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON — {e}"
    if not isinstance(rows, list) or not rows:
        return "Error: json_data must be a non-empty JSON array of objects."
    
    target = _safe_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    headers = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(str(tmp), str(target))
    return f"Exported CSV: {filename} ({len(rows)} rows, {len(headers)} columns)"

# Resources
@mcp.resource("report://{filename}")
def get_report(filename: str) -> str:
    """Read a saved report by URI."""
    target = _safe_path(filename)
    if not target.exists():
        return f"Error: Report '{filename}' not found."
    return target.read_text(encoding="utf-8")

# Prompts
@mcp.prompt()
def executive_summary(period: str, audience: str) -> str:
    """Generate an executive cost summary prompt."""
    return f"""Generate a {period} executive cost summary for {audience}.

Structure:
1. Total spend across all clouds (with MoM change %)
2. Top 5 services by cost
3. Notable changes or anomalies
4. Key recommendations (top 3 by savings potential)

Format as a clear, concise report. Use tables for data. 
Flag any data quality issues (partial periods, untagged spend).
Keep it under 1 page — executives skim, not read."""


@mcp.prompt()
def chargeback_report(team: str, period: str) -> str:
    """Generate a chargeback report prompt for a specific team."""
    return f"""Generate a chargeback report for team '{team}' covering {period}.

Include:
1. Total spend attributed to this team
2. Breakdown by cloud provider
3. Breakdown by service
4. Breakdown by environment (prod/staging/dev)
5. Shared infrastructure allocation (state the method used)
6. Comparison to previous period
7. Untagged resources that may belong to this team

Format as a structured report with tables. State all assumptions about cost allocation."""

if __name__ == "__main__":
    mcp.run()
