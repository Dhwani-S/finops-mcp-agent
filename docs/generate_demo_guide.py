"""Generate the FinOps Agent Demo Guide Word document."""
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from pathlib import Path

doc = Document()

# -- Styles --
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(11)
style.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

# ============================================================
# TITLE PAGE
# ============================================================
for _ in range(6):
    doc.add_paragraph()

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("FinOps Agent\nDemo Script")
run.bold = True
run.font.size = Pt(28)
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run("AI-Powered Cloud Cost Intelligence")
run.font.size = Pt(16)
run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

doc.add_paragraph()
date_p = doc.add_paragraph()
date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = date_p.add_run("June 2026  |  Confidential")
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

doc.add_page_break()

# ============================================================
# OVERVIEW
# ============================================================
doc.add_heading("Demo Overview", level=1)

doc.add_paragraph(
    "This demo showcases the FinOps Agent — an AI assistant that helps "
    "Cloud Excellence teams identify cost savings, compare cloud providers, "
    "and plan migrations across Azure, AWS, and GCP."
)

doc.add_paragraph(
    "The demo consists of three scenarios that tell a progressive story:"
)

items = [
    ("Find waste", "Analyze Azure VMs to uncover idle and oversized resources"),
    ("Compare options", "See how your AWS instances map to equivalent Azure and GCP VMs"),
    ("Plan a migration", "Estimate the cost impact of moving AWS workloads to GCP"),
]
for bold_text, rest in items:
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(f"{bold_text} — ")
    run.bold = True
    p.add_run(rest)

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Demo scope: ")
run.bold = True
p.add_run(
    'All queries are scoped to a single owner ("Jehan Wickramasuriya") '
    "to keep results focused. In production, the agent supports any owner, "
    "project, subscription, or the full organization."
)

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Talking point: ")
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
p.add_run(
    '"The agent connects directly to our live cost data in BigQuery and '
    'our recommendation databases. Everything you see is real data, not a mock."'
)

doc.add_page_break()

# ============================================================
# SCENARIO 1
# ============================================================
doc.add_heading("Scenario 1: Azure VM Rightsizing", level=1)

p = doc.add_paragraph()
run = p.add_run("What you type: ")
run.bold = True

p2 = doc.add_paragraph()
run = p2.add_run('"Run a VM and disk rightsizing analysis on my Azure resources"')
run.italic = True
run.font.size = Pt(12)

doc.add_heading("What happens", level=2)
doc.add_paragraph(
    "The agent asks who you want to analyze. Select "
    '"Specific project or owner" and type "Jehan Wickramasuriya". '
    "It then estimates the query cost (~$0.005) and asks for approval before "
    "scanning the data."
)

doc.add_heading("What the agent does behind the scenes", level=2)
steps = [
    "Queries 30 days of Azure VM utilization data (CPU and memory) from BigQuery",
    "Runs a proprietary rightsizing engine that applies P95 utilization rules",
    "Flags idle VMs, oversized VMs, and cross-family optimization opportunities",
    "Calculates potential monthly savings for each recommendation",
]
for s in steps:
    doc.add_paragraph(s, style="List Number")

doc.add_heading("Key results to highlight", level=2)

table = doc.add_table(rows=4, cols=2, style="Light Shading Accent 1")
table.alignment = WD_TABLE_ALIGNMENT.CENTER
data = [
    ("Total VMs Analyzed", "378"),
    ("VMs with Findings", "145"),
    ("Potential Monthly Savings", "$12,786 /month"),
    ("Top Finding", "Idle VMs costing $134/month each — candidates for deletion"),
]
for i, (k, v) in enumerate(data):
    table.rows[i].cells[0].text = k
    table.rows[i].cells[1].text = v
    if i == 2:
        for paragraph in table.rows[i].cells[1].paragraphs:
            for run in paragraph.runs:
                run.bold = True

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Talking point: ")
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
p.add_run(
    '"In under a minute, the agent analyzed 378 VMs, identified 145 with '
    "optimization opportunities, and found nearly $13,000 in monthly savings. "
    "That's over $150,000 annually — just for one owner's Azure resources.\""
)

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Transition: ")
run.bold = True
p.add_run(
    '"Now that we know where the waste is in Azure, let\'s see how our '
    'AWS resources compare across clouds."'
)

doc.add_page_break()

# ============================================================
# SCENARIO 2
# ============================================================
doc.add_heading("Scenario 2: Cross-Cloud Instance Comparison", level=1)

p = doc.add_paragraph()
run = p.add_run("What you type: ")
run.bold = True

p2 = doc.add_paragraph()
run = p2.add_run('"Compare my top AWS EC2 instances against equivalent Azure and GCP VMs"')
run.italic = True
run.font.size = Pt(12)

doc.add_paragraph(
    'The agent remembers the previous scope and asks if you want to continue '
    'with Jehan Wickramasuriya. Say yes.'
)

doc.add_heading("What happens", level=2)
doc.add_paragraph(
    "The agent finds the top 5 AWS EC2 instance types by cost, then maps each "
    "one to its closest equivalent VM on Azure and GCP based on vCPUs, memory, "
    "and workload type (including GPU instances)."
)

doc.add_heading("Key results to highlight", level=2)

table = doc.add_table(rows=6, cols=5, style="Light Shading Accent 1")
table.alignment = WD_TABLE_ALIGNMENT.CENTER
headers = ["AWS Instance", "Monthly Cost", "Azure Equivalent", "GCP Equivalent", "vCPUs / Memory"]
for i, h in enumerate(headers):
    table.rows[0].cells[i].text = h
    for paragraph in table.rows[0].cells[i].paragraphs:
        for run in paragraph.runs:
            run.bold = True

rows_data = [
    ("t3.xlarge", "$22,744", "Standard_B4ms", "e2-standard-4", "4 / 16 GiB"),
    ("g4dn.4xlarge", "$9,494", "NC16as_T4_v3", "n1-standard-16 + T4 GPU", "16 / 110 GiB"),
    ("g4dn.2xlarge", "$7,854", "NC8as_T4_v3", "n1-standard-8 + T4 GPU", "8 / 56 GiB"),
    ("g4dn.xlarge", "$6,692", "NC4as_T4_v3", "n1-standard-4 + T4 GPU", "4 / 28 GiB"),
    ("m6i.large", "$5,036", "Standard_D2s_v5", "n2-standard-2", "2 / 8 GiB"),
]
for r, row_data in enumerate(rows_data):
    for c, val in enumerate(row_data):
        table.rows[r + 1].cells[c].text = val

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Talking point: ")
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
p.add_run(
    '"The agent automatically maps instance types across all three clouds — '
    "including complex GPU instances like the g4dn series. This kind of "
    "comparison would normally take a cloud architect hours to research. "
    'The agent does it in seconds."'
)

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Transition: ")
run.bold = True
p.add_run(
    '"Now that we can see the equivalents, the natural question is: '
    'what would it actually cost if we moved these workloads?"'
)

doc.add_page_break()

# ============================================================
# SCENARIO 3
# ============================================================
doc.add_heading("Scenario 3: What-If Migration Analysis", level=1)

p = doc.add_paragraph()
run = p.add_run("What you type: ")
run.bold = True

p2 = doc.add_paragraph()
run = p2.add_run(
    '"What if we migrate my top 5 AWS workloads to GCP? Show estimated cost impact"'
)
run.italic = True
run.font.size = Pt(12)

doc.add_heading("What happens", level=2)
doc.add_paragraph(
    "The agent takes the cost data from the previous query, applies "
    "industry-standard pricing ratios for equivalent GCP services, and "
    "projects the savings over a 12-month period."
)

doc.add_heading("Key results to highlight", level=2)

table = doc.add_table(rows=4, cols=2, style="Light Shading Accent 1")
table.alignment = WD_TABLE_ALIGNMENT.CENTER
summary_data = [
    ("Current Annual AWS Cost", "$621,835"),
    ("Projected Annual GCP Cost", "$514,913"),
    ("Estimated Annual Savings", "$106,922"),
    ("Savings Percentage", "17.2%"),
]
for i, (k, v) in enumerate(summary_data):
    table.rows[i].cells[0].text = k
    table.rows[i].cells[1].text = v
    if i >= 2:
        for paragraph in table.rows[i].cells[1].paragraphs:
            for run in paragraph.runs:
                run.bold = True

doc.add_paragraph()

table2 = doc.add_table(rows=6, cols=4, style="Light Shading Accent 1")
table2.alignment = WD_TABLE_ALIGNMENT.CENTER
headers2 = ["Workload", "Current (AWS/mo)", "Projected (GCP/mo)", "Monthly Savings"]
for i, h in enumerate(headers2):
    table2.rows[0].cells[i].text = h
    for paragraph in table2.rows[0].cells[i].paragraphs:
        for run in paragraph.runs:
            run.bold = True

migration_data = [
    ("t3.xlarge", "$22,744", "$18,195", "$4,549"),
    ("g4dn.4xlarge", "$9,494", "$7,975", "$1,519"),
    ("g4dn.2xlarge", "$7,854", "$6,597", "$1,257"),
    ("g4dn.xlarge", "$6,692", "$5,621", "$1,071"),
    ("m6i.large", "$5,036", "$4,281", "$755"),
]
for r, row_data in enumerate(migration_data):
    for c, val in enumerate(row_data):
        table2.rows[r + 1].cells[c].text = val

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Talking point: ")
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
p.add_run(
    '"By migrating just these five workloads from AWS to GCP, we could '
    "save over $100,000 per year — a 17% reduction. And this is just one "
    "owner's resources. Across the organization, the potential is "
    'significantly larger."'
)

doc.add_page_break()

# ============================================================
# CLOSING / SUMMARY
# ============================================================
doc.add_heading("Demo Summary", level=1)

doc.add_paragraph(
    "In this demo, the FinOps Agent demonstrated three core capabilities:"
)

closing = [
    (
        "Cost Optimization",
        "Identified $12,786/month in Azure VM savings by analyzing "
        "utilization data and applying rightsizing rules",
    ),
    (
        "Cross-Cloud Intelligence",
        "Mapped AWS instance types to Azure and GCP equivalents — "
        "including GPU workloads — in seconds",
    ),
    (
        "Migration Planning",
        "Projected $106,922 in annual savings from an AWS-to-GCP migration "
        "of the top 5 workloads",
    ),
]
for bold_text, rest in closing:
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(f"{bold_text}: ")
    run.bold = True
    p.add_run(rest)

doc.add_paragraph()
p = doc.add_paragraph()
run = p.add_run("Closing statement: ")
run.bold = True
run.font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)
p.add_run(
    '"The FinOps Agent turns hours of manual cloud cost analysis into '
    "a conversation. It connects to live data, understands multi-cloud "
    "environments, and gives actionable recommendations — all through "
    'natural language."'
)

# ============================================================
# SAVE
# ============================================================
out = Path(__file__).resolve().parent / "FinOps_Agent_Demo_Guide.docx"
doc.save(str(out))
print(f"Saved to {out}")
