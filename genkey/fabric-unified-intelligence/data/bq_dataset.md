## **QuickBooks Tax Optimization Data Architecture**

> Intuit uses this schema to track customer tax returns, identify optimization
> opportunities (e.g., Section 174, R&D credits), and ensure every feature
> in the "Arden Tax Shield" rollout is fully compliant with IRS regulations.

### Pre-requisite

Check if the dataset `quickbooks_tax_intelligence_demo` exists in BigQuery. If not, create it.

---

### **1. Core Table Structures**

#### **A. Tax Returns Table (`tax_returns`)**

*Tracks customer tax filings and high-level financial snapshots.*

| Column | Type | Description |
|--------|------|-------------|
| `return_id` | `STRING` | Unique return ID (required) |
| `customer_id` | `STRING` | Unique QuickBooks customer ID |
| `tax_year` | `INT64` | e.g., 2026 |
| `entity_type` | `STRING` | S-Corp, LLC, Sole Proprietorship |
| `total_revenue` | `NUMERIC` | Annual revenue |
| `total_expenses` | `NUMERIC` | Annual expenses |
| `rd_expenses` | `NUMERIC` | Expenses eligible for R&D credits |
| `state_of_filing` | `STRING` | Primary state for tax jurisdiction |
| `status` | `STRING` | Draft, Ready for Review, Filed |
| `last_updated` | `TIMESTAMP` | Last modification timestamp |

#### **B. Tax Optimizations Table (`tax_optimizations`)**

*Identified opportunities for tax savings based on regulatory data.*

| Column | Type | Description |
|--------|------|-------------|
| `optimization_id` | `STRING` | Unique ID |
| `return_id` | `STRING` | Linked return |
| `code_section` | `STRING` | e.g., "Section 174", "Section 41" |
| `description` | `STRING` | Summary of the optimization |
| `estimated_savings` | `NUMERIC` | Potential tax saving amount |
| `confidence_score` | `NUMERIC` | AI confidence (0.0 - 1.0) |
| `mcp_source` | `STRING` | Link to Data.gov or IRS source |

---

## **2. Identifying & Managing Optimization Tiers**

The **`optimization_health_view`** classifies potential tax savings based on the confidence score and the risk profile.

### **Optimization Risk Tiers**

| Tier | Range | Recommendation |
| --- | --- | --- |
| **High Confidence** | 0.9 – 1.0 | Automatic application in the "Arden Tax Shield". |
| **Medium Confidence** | 0.7 – 0.89 | Requires CPA-review flag in the UI. |
| **High Risk** | < 0.7 | Requires manual evidence gathering and audit trail. |

---

## **3. Strategic Recommendations**

*   **R&D Credit Analysis**: Use the `rd_expenses` field to automatically flag users eligible for Section 41 credits.
*   **Section 174 Amortization**: Automatically calculate amortization schedules for software development costs based on the new 2026 guidelines.
*   **Audit Readiness**: Maintain a 1:1 mapping between `optimization_id` and the `mcp_source` to provide instant audit trails.
