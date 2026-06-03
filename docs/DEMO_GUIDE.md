# FinOps Agent — Demo Script

**AI-Powered Cloud Cost Intelligence**

June 2026 | Confidential

---

## Demo Overview

This demo showcases the FinOps Agent — an AI assistant that helps Cloud Excellence teams identify cost savings, compare cloud providers, and plan migrations across Azure, AWS, and GCP.

The demo consists of three scenarios that tell a progressive story:

- **Find waste** — Analyze Azure VMs to uncover idle and oversized resources
- **Compare options** — See how your AWS instances map to equivalent Azure and GCP VMs
- **Plan a migration** — Estimate the cost impact of moving AWS workloads to GCP

**Demo scope:** All queries are scoped to a single owner ("Jehan Wickramasuriya") to keep results focused. In production, the agent supports any owner, project, subscription, or the full organization.

> 💬 **Talking point:** *"The agent connects directly to our live cost data in BigQuery and our recommendation databases. Everything you see is real data, not a mock."*

---

## Scenario 1: Azure VM Rightsizing

**What you type:**

> *"Run a VM and disk rightsizing analysis on my Azure resources"*

### What happens

The agent asks who you want to analyze. Select "Specific project or owner" and type "Jehan Wickramasuriya". It then estimates the query cost (~$0.005) and asks for approval before scanning the data.

### What the agent does behind the scenes

1. Queries 30 days of Azure VM utilization data (CPU and memory) from BigQuery
2. Runs a proprietary rightsizing engine that applies P95 utilization rules
3. Flags idle VMs, oversized VMs, and cross-family optimization opportunities
4. Calculates potential monthly savings for each recommendation

### Key results to highlight

| Metric | Value |
|---|---|
| Total VMs Analyzed | 378 |
| VMs with Findings | 145 |
| Potential Monthly Savings | **$12,786 /month** |
| Top Finding | Idle VMs costing $134/month each — candidates for deletion |

> 💬 **Talking point:** *"In under a minute, the agent analyzed 378 VMs, identified 145 with optimization opportunities, and found nearly $13,000 in monthly savings. That's over $150,000 annually — just for one owner's Azure resources."*

**Transition:** *"Now that we know where the waste is in Azure, let's see how our AWS resources compare across clouds."*

---

## Scenario 2: Cross-Cloud Instance Comparison

**What you type:**

> *"Compare my top AWS EC2 instances against equivalent Azure and GCP VMs"*

The agent remembers the previous scope and asks if you want to continue with Jehan Wickramasuriya. Say yes.

### What happens

The agent finds the top 5 AWS EC2 instance types by cost, then maps each one to its closest equivalent VM on Azure and GCP based on vCPUs, memory, and workload type (including GPU instances).

### Key results to highlight

| AWS Instance | Monthly Cost | Azure Equivalent | GCP Equivalent | vCPUs / Memory |
|---|---|---|---|---|
| t3.xlarge | $22,744 | Standard_B4ms | e2-standard-4 | 4 / 16 GiB |
| g4dn.4xlarge | $9,494 | NC16as_T4_v3 | n1-standard-16 + T4 GPU | 16 / 110 GiB |
| g4dn.2xlarge | $7,854 | NC8as_T4_v3 | n1-standard-8 + T4 GPU | 8 / 56 GiB |
| g4dn.xlarge | $6,692 | NC4as_T4_v3 | n1-standard-4 + T4 GPU | 4 / 28 GiB |
| m6i.large | $5,036 | Standard_D2s_v5 | n2-standard-2 | 2 / 8 GiB |

> 💬 **Talking point:** *"The agent automatically maps instance types across all three clouds — including complex GPU instances like the g4dn series. This kind of comparison would normally take a cloud architect hours to research. The agent does it in seconds."*

**Transition:** *"Now that we can see the equivalents, the natural question is: what would it actually cost if we moved these workloads?"*

---

## Scenario 3: What-If Migration Analysis

**What you type:**

> *"What if we migrate my top 5 AWS workloads to GCP? Show estimated cost impact"*

### What happens

The agent takes the cost data from the previous query, applies industry-standard pricing ratios for equivalent GCP services, and projects the savings over a 12-month period.

### Key results to highlight

| Metric | Value |
|---|---|
| Current Annual AWS Cost | $621,835 |
| Projected Annual GCP Cost | $514,913 |
| Estimated Annual Savings | **$106,922** |
| Savings Percentage | **17.2%** |

| Workload | Current (AWS/mo) | Projected (GCP/mo) | Monthly Savings |
|---|---|---|---|
| t3.xlarge | $22,744 | $18,195 | $4,549 |
| g4dn.4xlarge | $9,494 | $7,975 | $1,519 |
| g4dn.2xlarge | $7,854 | $6,597 | $1,257 |
| g4dn.xlarge | $6,692 | $5,621 | $1,071 |
| m6i.large | $5,036 | $4,281 | $755 |

> 💬 **Talking point:** *"By migrating just these five workloads from AWS to GCP, we could save over $100,000 per year — a 17% reduction. And this is just one owner's resources. Across the organization, the potential is significantly larger."*

---

## Demo Summary

In this demo, the FinOps Agent demonstrated three core capabilities:

- **Cost Optimization:** Identified $12,786/month in Azure VM savings by analyzing utilization data and applying rightsizing rules
- **Cross-Cloud Intelligence:** Mapped AWS instance types to Azure and GCP equivalents — including GPU workloads — in seconds
- **Migration Planning:** Projected $106,922 in annual savings from an AWS-to-GCP migration of the top 5 workloads

> 💬 **Closing statement:** *"The FinOps Agent turns hours of manual cloud cost analysis into a conversation. It connects to live data, understands multi-cloud environments, and gives actionable recommendations — all through natural language."*
