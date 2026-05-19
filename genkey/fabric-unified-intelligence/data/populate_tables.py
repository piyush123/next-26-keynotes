#!/usr/bin/env python3
"""
Populate the tax_returns and tax_optimizations BigQuery tables with
realistic sample records for the Intuit PM demo.

The data is designed to showcase the "Arden Tax Shield" narrative,
including R&D credits, Section 174 amortization, and various risk tiers.

Prerequisites:
  - google-cloud-bigquery  (pip install google-cloud-bigquery)
  - GCP credentials configured  (gcloud auth application-default login)
"""

import os
import random
import subprocess
import uuid
from datetime import datetime, timezone

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
if not PROJECT_ID:
    result = subprocess.run(
        ["gcloud", "config", "get-value", "project"],
        capture_output=True, text=True,
    )
    PROJECT_ID = result.stdout.strip()

if not PROJECT_ID:
    raise SystemExit(
        "ERROR: No GCP project configured.\n"
        "  Set GCP_PROJECT_ID or run: gcloud config set project <PROJECT_ID>"
    )

DATASET = "quickbooks_tax_intelligence_demo"
TABLE_RETURNS = f"{PROJECT_ID}.{DATASET}.tax_returns"
TABLE_OPTIMIZATIONS = f"{PROJECT_ID}.{DATASET}.tax_optimizations"

NOW = datetime.now(timezone.utc)
CURRENT_YEAR = NOW.year

random.seed(42)  # reproducible data

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
ENTITY_TYPES = ["S-Corp", "LLC", "Sole Proprietorship", "C-Corp"]
STATES = ["CA", "NY", "TX", "FL", "WA", "IL", "MA"]
STATUSES = ["Draft", "Ready for Review", "Filed"]

OPTIMIZATION_TEMPLATES = [
    {
        "code_section": "Section 174",
        "description": "Amortization of Software Development Costs",
        "base_savings": 15000,
        "risk": "low"
    },
    {
        "code_section": "Section 41",
        "description": "R&D Tax Credit for Incremental Research",
        "base_savings": 25000,
        "risk": "medium"
    },
    {
        "code_section": "Section 199A",
        "description": "Qualified Business Income Deduction",
        "base_savings": 5000,
        "risk": "low"
    },
    {
        "code_section": "Section 179",
        "description": "Election to Expense Certain Depreciable Assets",
        "base_savings": 12000,
        "risk": "low"
    },
    {
        "code_section": "Work Opportunity Tax Credit",
        "description": "Credit for hiring individuals from target groups",
        "base_savings": 2400,
        "risk": "high"
    }
]

def _customer_id(n: int) -> str:
    return f"CUST-{n:05d}"

def _return_id(cust_id: str, year: int) -> str:
    return f"RET-{cust_id}-{year}"

def _jitter(base: float, pct: float = 0.2) -> float:
    return round(base * random.uniform(1 - pct, 1 + pct), 2)

# ---------------------------------------------------------------------------
# 1. Build tax_returns rows
# ---------------------------------------------------------------------------
return_rows = []
optimization_rows = []

for i in range(1, 51):
    cust_id = _customer_id(i)
    ret_id = _return_id(cust_id, CURRENT_YEAR)
    
    revenue = _jitter(500000, 0.8)
    expenses = revenue * random.uniform(0.4, 0.8)
    rd_expenses = expenses * random.uniform(0.05, 0.2) if random.random() > 0.4 else 0
    
    return_rows.append({
        "return_id": ret_id,
        "customer_id": cust_id,
        "tax_year": CURRENT_YEAR,
        "entity_type": random.choice(ENTITY_TYPES),
        "total_revenue": round(revenue, 2),
        "total_expenses": round(expenses, 2),
        "rd_expenses": round(rd_expenses, 2),
        "state_of_filing": random.choice(STATES),
        "status": random.choice(STATUSES),
        "last_updated": NOW.isoformat(),
    })
    
    # Generate optimizations for this return
    num_opts = random.randint(1, 3)
    selected_opts = random.sample(OPTIMIZATION_TEMPLATES, num_opts)
    
    for opt in selected_opts:
        savings = _jitter(opt["base_savings"])
        
        # Adjust confidence score based on risk template
        if opt["risk"] == "low":
            conf = random.uniform(0.9, 1.0)
        elif opt["risk"] == "medium":
            conf = random.uniform(0.7, 0.89)
        else:
            conf = random.uniform(0.5, 0.69)
            
        optimization_rows.append({
            "optimization_id": f"OPT-{uuid.uuid4().hex[:8].upper()}",
            "return_id": ret_id,
            "code_section": opt["code_section"],
            "description": opt["description"],
            "estimated_savings": round(savings, 2),
            "confidence_score": round(conf, 2),
            "mcp_source": f"https://www.irs.gov/newsroom/search?search_type=news&q={opt['code_section'].replace(' ', '+')}"
        })

print(f"  tax_returns: {len(return_rows)} rows prepared")
print(f"  tax_optimizations: {len(optimization_rows)} rows prepared")

# ---------------------------------------------------------------------------
# 3. Insert into BigQuery
# ---------------------------------------------------------------------------
try:
    client = bigquery.Client(project=PROJECT_ID)

    print(f"\n>>> Inserting into {TABLE_RETURNS} ...")
    errors = client.insert_rows_json(TABLE_RETURNS, return_rows)
    if errors:
        print(f"  ERROR inserting return rows: {errors}")
    else:
        print(f"  ✓ {len(return_rows)} rows inserted into tax_returns")

    print(f"\n>>> Inserting into {TABLE_OPTIMIZATIONS} ...")
    errors = client.insert_rows_json(TABLE_OPTIMIZATIONS, optimization_rows)
    if errors:
        print(f"  ERROR inserting optimization rows: {errors}")
    else:
        print(f"  ✓ {len(optimization_rows)} rows inserted into tax_optimizations")

    print("\nDone!")
except Exception as e:
    print(f"  CRITICAL ERROR: {e}")
    print("  Note: Ensure you have run 'setup_bigquery.sh' (updated for tax schema) first.")
