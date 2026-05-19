#!/bin/bash
# =============================================================================
# BigQuery Setup Script — QuickBooks Tax Optimization Data Architecture
#
# This script creates the dataset, tables, and a "Optimization Health" view
# as described in bq_dataset.md.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
DATASET="quickbooks_tax_intelligence_demo"
LOCATION="${BQ_LOCATION:-US}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: No GCP project configured."
  echo "  Set the GCP_PROJECT_ID env var or run: gcloud config set project <PROJECT_ID>"
  exit 1
fi

echo "============================================="
echo " BigQuery Setup — QuickBooks Tax"
echo " Project : ${PROJECT_ID}"
echo " Dataset : ${DATASET}"
echo " Location: ${LOCATION}"
echo "============================================="

# ---------------------------------------------------------------------------
# 1. Create the dataset
# ---------------------------------------------------------------------------
echo ""
echo ">>> Checking / creating dataset '${DATASET}' ..."

if bq --project_id="${PROJECT_ID}" show "${DATASET}" > /dev/null 2>&1; then
  echo "    Dataset '${DATASET}' already exists — skipping."
else
  bq --project_id="${PROJECT_ID}" mk \
    --dataset \
    --location="${LOCATION}" \
    --description="QuickBooks Tax Optimization demo dataset" \
    "${DATASET}"
  echo "    Dataset '${DATASET}' created."
fi

# ---------------------------------------------------------------------------
# 2. Create the tax_returns table
# ---------------------------------------------------------------------------
TABLE_RETURNS="${DATASET}.tax_returns"

echo ""
echo ">>> Creating table '${TABLE_RETURNS}' ..."

bq --project_id="${PROJECT_ID}" mk \
  --table \
  --description="Tracks customer tax filings and financial snapshots" \
  "${TABLE_RETURNS}" \
  'return_id:STRING,
   customer_id:STRING,
   tax_year:INT64,
   entity_type:STRING,
   total_revenue:NUMERIC,
   total_expenses:NUMERIC,
   rd_expenses:NUMERIC,
   state_of_filing:STRING,
   status:STRING,
   last_updated:TIMESTAMP' \
  2>/dev/null \
  && echo "    Table '${TABLE_RETURNS}' created." \
  || echo "    Table '${TABLE_RETURNS}' already exists — skipping."

# ---------------------------------------------------------------------------
# 3. Create the tax_optimizations table
# ---------------------------------------------------------------------------
TABLE_OPTIMIZATIONS="${DATASET}.tax_optimizations"

echo ""
echo ">>> Creating table '${TABLE_OPTIMIZATIONS}' ..."

bq --project_id="${PROJECT_ID}" mk \
  --table \
  --description="Identified opportunities for tax savings" \
  "${TABLE_OPTIMIZATIONS}" \
  'optimization_id:STRING,
   return_id:STRING,
   code_section:STRING,
   description:STRING,
   estimated_savings:NUMERIC,
   confidence_score:NUMERIC,
   mcp_source:STRING' \
  2>/dev/null \
  && echo "    Table '${TABLE_OPTIMIZATIONS}' created." \
  || echo "    Table '${TABLE_OPTIMIZATIONS}' already exists — skipping."

# ---------------------------------------------------------------------------
# 4. Create the optimization_health_view
# ---------------------------------------------------------------------------
VIEW_OPTIMIZATION_HEALTH="${DATASET}.optimization_health_view"

echo ""
echo ">>> Creating view '${VIEW_OPTIMIZATION_HEALTH}' ..."

bq --project_id="${PROJECT_ID}" mk \
  --use_legacy_sql=false \
  --view "
SELECT
  r.customer_id,
  r.entity_type,
  o.optimization_id,
  o.return_id,
  o.code_section,
  o.description,
  o.estimated_savings,
  o.confidence_score,
  CASE
    WHEN o.confidence_score >= 0.9 THEN 'High Confidence'
    WHEN o.confidence_score >= 0.7 THEN 'Medium Confidence'
    ELSE 'High Risk'
  END AS risk_tier,
  CASE
    WHEN o.confidence_score >= 0.9 THEN 'Automatic application in Arden Tax Shield'
    WHEN o.confidence_score >= 0.7 THEN 'Requires CPA-review flag'
    ELSE 'Requires manual evidence gathering'
  END AS recommendation,
  o.mcp_source
FROM
  \`${PROJECT_ID}.${DATASET}.tax_optimizations\` AS o
JOIN
  \`${PROJECT_ID}.${DATASET}.tax_returns\` AS r
  ON o.return_id = r.return_id
ORDER BY
  o.estimated_savings DESC
" \
  --description="Classifies tax optimizations by risk tier and providing recommendations" \
  "${VIEW_OPTIMIZATION_HEALTH}" \
  2>/dev/null \
  && echo "    View '${VIEW_OPTIMIZATION_HEALTH}' created." \
  || echo "    View '${VIEW_OPTIMIZATION_HEALTH}' already exists — skipping."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Setup complete!"
echo " Resources created in ${PROJECT_ID}:"
echo "   • ${DATASET}                  (dataset)"
echo "   • ${TABLE_RETURNS}            (table)"
echo "   • ${TABLE_OPTIMIZATIONS}       (table)"
echo "   • ${VIEW_OPTIMIZATION_HEALTH}  (view)"
echo "============================================="
