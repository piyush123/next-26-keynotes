#!/usr/bin/env python3
"""
Generate a mock tax return catalog for the Intuit PM demo.
This replicates the structure of the furniture global catalog
but for tax optimization features and customer segments.
"""

import pandas as pd
import random
import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPTIMIZATION_SECTIONS = [
    "Section 174 (Software Dev)",
    "Section 41 (R&D Credits)",
    "Section 199A (QBI)",
    "Section 179 (Expensing)",
    "Section 168(k) (Bonus Depreciation)",
    "Work Opportunity Tax Credit",
    "Energy Efficient Commercial Bldgs (179D)"
]

ENTITY_TYPES = ["S-Corp", "LLC", "Sole Proprietorship", "C-Corp"]

# ---------------------------------------------------------------------------
# Data Generation
# ---------------------------------------------------------------------------
data = []
for i in range(1, 101):
    entity = random.choice(ENTITY_TYPES)
    revenue = round(random.uniform(100000, 5000000), 2)
    
    # Generate 1-2 potential optimizations per segment
    opts = random.sample(OPTIMIZATION_SECTIONS, random.randint(1, 2))
    
    for opt in opts:
        savings_pct = random.uniform(0.02, 0.08)
        data.append({
            "Segment_ID": f"SEG-{i:03d}",
            "Entity_Type": entity,
            "Avg_Revenue": revenue,
            "Optimization_Focus": opt,
            "Target_Saving_Pct": round(savings_pct, 4),
            "Estimated_Segment_Benefit": round(revenue * savings_pct, 2),
            "Arden_Shield_Eligibility": "High" if savings_pct > 0.05 else "Medium"
        })

df = pd.DataFrame(data)

# Save as Excel and CSV
df.to_excel("global_tax_optimization_catalog.xlsx", index=False)
df.to_csv("global_tax_optimization_catalog.csv", index=False)

print("✓ Created global_tax_optimization_catalog.xlsx and .csv")
