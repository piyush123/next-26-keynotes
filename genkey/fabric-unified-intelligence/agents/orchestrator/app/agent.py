# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import datetime
import json as _json
import logging
import os
import pathlib
import re
import uuid

import google.auth
import google.auth.transport.requests
import httpx
import requests
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from dotenv import load_dotenv
from app.a2ui_schema import A2UI_SCHEMA, ORCHESTRATOR_A2UI_EXAMPLE
from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv(override=True)

# Dynamic year tokens used in prompt templates so trend references stay current.
_CURRENT_YEAR = datetime.date.today().year
_NEXT_YEAR = _CURRENT_YEAR + 1


def load_prompt(prompt_name: str) -> str:
    prompt_path = pathlib.Path(__file__).parent / "prompts" / prompt_name
    try:
        text = prompt_path.read_text()
        # Replace year placeholders so prompts always reference the current year.
        return text.replace("{current_year}", str(_CURRENT_YEAR)).replace(
            "{next_year}", str(_NEXT_YEAR)
        )
    except FileNotFoundError:
        logger.warning("Prompt file %s not found.", prompt_name)
        return ""


system_prompt = load_prompt("system_prompt.md")
system_instructions = load_prompt("system_instructions.md")
model_id = os.getenv("ADK_MODEL", "gemini-3-flash-preview")


# ---------------------------------------------------------------------------
# Shared credentials — single google.auth.default() call for the whole module.
# Reused by _extract_token() (for access tokens) and for project_id discovery.
# Fixes C6/E5: eliminates duplicate google.auth.default() calls.
# ---------------------------------------------------------------------------
_cached_adc_credentials, _default_project_id = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)

# Use setdefault so .env values are respected; only fill in if not already set.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _default_project_id or "")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# ---------------------------------------------------------------------------
# E3: Initialize aiplatform once at module level (lazy, on first import).
# ---------------------------------------------------------------------------
_aiplatform_initialized = False


def _ensure_aiplatform_init() -> None:
    """Initialize the Vertex AI SDK exactly once."""
    global _aiplatform_initialized
    if not _aiplatform_initialized:
        from google.cloud import aiplatform

        aiplatform.init()
        _aiplatform_initialized = True


# ---------------------------------------------------------------------------
# E1/E2: Module-level A2A client cache — reuses httpx connections and
# avoids re-discovering the agent card on every call to the same endpoint.
# ---------------------------------------------------------------------------
_a2a_client_cache: dict[str, tuple[httpx.AsyncClient, object]] = {}
_a2a_client_locks: dict[str, asyncio.Lock] = {}


async def _extract_token(tool_context: ToolContext) -> str:
    """Extracts an identity token for the current environment."""
    from google.auth.transport.requests import Request

    cached_token = tool_context.state.get("_identity_token")
    if cached_token:
        return cached_token

    try:
        if not _cached_adc_credentials.valid:
            _cached_adc_credentials.refresh(Request())

        token = _cached_adc_credentials.token
        tool_context.state["_identity_token"] = token
        return token
    except Exception as e:
        logger.error("Failed to extract token: %s", e)
        return ""


async def _send_a2a_message(endpoint_url: str, query: str) -> str:
    """Sends a message to an A2A-compatible agent endpoint."""
    global _a2a_client_cache, _a2a_client_locks

    if endpoint_url not in _a2a_client_locks:
        _a2a_client_locks[endpoint_url] = asyncio.Lock()

    async with _a2a_client_locks[endpoint_url]:
        if endpoint_url not in _a2a_client_cache:
            card_url = f"{endpoint_url.rstrip('/')}/.well-known/agent-card.json"
            client_config = ClientConfig(agent_card_url=card_url)
            http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
            a2a_client = await ClientFactory.from_config(
                client_config, http_client=http_client
            )
            _a2a_client_cache[endpoint_url] = (http_client, a2a_client)

        _, a2a_client = _a2a_client_cache[endpoint_url]

    message = Message(role=Role.USER, parts=[Part(text=TextPart(text=query))])

    try:
        response_iter = await a2a_client.generate_content(message)
        full_text = ""
        async for chunk in response_iter:
            if chunk.parts:
                for part in chunk.parts:
                    if part.text:
                        full_text += part.text.text
        return full_text
    except Exception as e:
        logger.exception("Error during A2A message exchange with %s", endpoint_url)
        return f"Error: A2A communication failed: {e}"


def _call_data_insight_agent_sync(query: str, access_token: str) -> str:
    """Calls the BigQuery Conversational Analytics Data Agent (sync wrapper)."""
    project_id = os.environ.get("BQ_DATA_AGENT_PROJECT")
    agent_id = os.environ.get("BQ_DATA_AGENT_ID")
    location = os.environ.get("BQ_DATA_AGENT_LOCATION", "global")

    if not all([project_id, agent_id]):
        return "Error: BQ_DATA_AGENT_PROJECT or BQ_DATA_AGENT_ID is not set."

    url = f"https://geminidataanalytics.googleapis.com/v1/projects/{project_id}/locations/{location}/dataAgents/{agent_id}:query"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        return data.get("answer", data.get("response", str(data)))
    except Exception as e:
        logger.error("Error calling BigQuery Data Agent: %s", e)
        return f"Error: Failed to query internal data: {e}"


async def query_regulatory_research_agent(
    query: str,
    tool_context: ToolContext,
) -> str:
    """Queries the Market Research Agent for regulatory updates and tax law changes.

    This tool uses MCP to access authoritative sources like Data.gov.
    Use this to identify new tax optimizations or compliance requirements.

    Args:
        query: The regulatory question or topic to investigate.
        tool_context: ADK tool context.
    """
    # --- Duplicate-call guard -------------
    cached = tool_context.state.get("_regulatory_result")
    if cached:
        return cached

    endpoint_url = os.environ.get("MARKET_RESEARCH_AGENT_URL", "")
    
    # --- Standalone/Mock Mode Support ---
    if not endpoint_url or endpoint_url.lower() == "mock":
        logger.info("Standalone mode: Returning mock regulatory research data.")
        result = (
            "## 🔍 Regulatory Research Report: Section 174 Updates\n"
            "**Source**: IRS.gov & Data.gov (via MCP)\n"
            "**Key Findings**:\n"
            "- For the " + str(_CURRENT_YEAR) + " tax year, Section 174 mandates 5-year amortization "
            "for domestic software development costs.\n"
            "- **De Minimis Safe Harbor**: Small businesses with less than $10M in revenue "
            "can elect to expense up to $50,000 of these costs if tracked at the project level.\n"
            "- **Impact**: QuickBooks users in the S-Corp segment are most affected by the new "
            "tracking requirements."
        )
        tool_context.state["_regulatory_result"] = result
        return result

    result = await _send_a2a_message(endpoint_url, query)
    tool_context.state["_regulatory_result"] = result
    return result


async def query_tt_coordinator(query: str, tool_context: ToolContext) -> str:
    """Queries the TT Coordinator for specialized tax data analysis and return optimization.

    This agent specializes in mapping customer data to tax benefits and
    identifying optimization opportunities in QuickBooks.

    Args:
        query: The request for tax data analysis.
        tool_context: ADK tool context.
    """
    # --- Duplicate-call guard -------------
    cached = tool_context.state.get("_tt_result")
    if cached:
        return cached

    project_id = os.environ.get("BQ_DATA_AGENT_PROJECT", "")
    
    # --- Standalone/Mock Mode Support ---
    if not project_id or project_id.lower() == "mock":
        logger.info("Standalone mode: Returning mock TT Coordinator analysis.")
        result = (
            "## 📊 TT Coordinator: Customer Segment Analysis\n"
            "**Segment**: QuickBooks Small Business S-Corps\n"
            "**Sample Size**: 50,000 active users\n\n"
            "### Optimization Metrics:\n"
            "- **Average R&D Spend**: $85,000 per user.\n"
            "- **Potential Arden Shield Benefit**: $12,400 average tax saving per user.\n"
            "- **Optimization Tier**: 82% of users are in the 'High Confidence' tier for Section 174."
        )
        tool_context.state["_tt_result"] = result
        return result

    access_token = await _extract_token(tool_context)
    if not access_token:
        return "Error: Could not retrieve an access token."
    
    result = await asyncio.to_thread(_call_data_insight_agent_sync, query, access_token)
    tool_context.state["_tt_result"] = result
    return result


async def validate_compliance(prd_content: str, tool_context: ToolContext) -> str:
    """Validates the Product Requirement Document (PRD) against Intuit Compliance Policies.

    This agent performs a deep scan of proposed features against Intuit's 
    Tax Accuracy, Data Privacy (GDPR/CCPA), and AI Ethics guidelines.

    Args:
        prd_content: The draft PRD content to validate.
        tool_context: ADK tool context.
    """
    # Mocking a high-fidelity compliance report for the demo
    return (
        "## 🛡️ Intuit Compliance Validation Report\n"
        "**Status**: ✅ PASSED\n"
        "**Timestamp**: " + datetime.datetime.now().isoformat() + "\n\n"
        "### Policy Checks:\n"
        "1. **[INT-TAX-829] Accuracy & Liability**: PASSED. 'The Arden Tax Shield' "
        "logic includes mandatory CPA-review flags for high-value optimizations.\n"
        "2. **[INT-PRIV-401] Data Minimization**: PASSED. PII is tokenized "
        "before being passed to the sub-agent orchestration layer.\n"
        "3. **[INT-ETH-005] AI Transparency**: PASSED. User UI will clearly "
        "identify AI-generated suggestions with a 'Confidence Score' indicator.\n\n"
        "**Summary**: The PRD aligns with all 2026 Intuit Governance standards. "
        "Proceeding to engineering handoff is authorized."
    )


async def handoff_to_dev(prd_context: str, tool_context: ToolContext) -> str:
    """Hands off the PRD context to the Dev Agent for mockup and code generation.

    Simulates an integration with Jira and the Intuit Developer Portal, 
    creating a trackable epic and passing the full 'Universal Context'.

    Args:
        prd_context: The finalized PRD and supporting data.
        tool_context: ADK tool context.
    """
    # Mocking a high-fidelity Jira handoff for the demo
    ticket_id = f"QB-TAX-{uuid.uuid4().hex[:4].upper()}"
    return (
        f"## 🚀 Engineering Handoff: {ticket_id}\n"
        f"**Target System**: Jira Enterprise (Intuit Instance)\n"
        f"**Action**: Created Epic [{ticket_id}] - Arden Tax Shield Implementation\n\n"
        "### Universal Context Transferred:\n"
        "- **Regulatory Data**: Section 174 Tax Code updates (Data.gov source linked).\n"
        "- **Optimisation Logic**: TT Coordinator return-mapping v2.4.\n"
        "- **Compliance Artifacts**: Validation report #829-A attached.\n\n"
        "**Next Steps**: Dev Agent is now generating a React-based dashboard "
        "mockup and provisioning the sandbox environment. You will receive a "
        "Slack notification when the 'Canvas Mockup' is ready for review."
    )


shared_model = Gemini(
    model=model_id,
    retry_options=types.HttpRetryOptions(attempts=3),
)

_A2UI_INSTRUCTIONS = f"""

---

## A2UI Rich UI Output

**IMPORTANT**: Only use A2UI output when you have successfully completed the full coordinated workflow (including handoff_to_dev) and have a PRD Google Doc and a Jira Task/Epic to link. For all other middle-turn responses, respond with plain text ONLY — do NOT include the `---a2ui_JSON---` delimiter or any A2UI JSON.

Your final output MUST include A2UI UI JSON ONLY at the very end of the full lifecycle run.
To generate the response, you MUST follow these rules:

1. Your response MUST be in two parts, separated by the delimiter: `---a2ui_JSON---`.
2. The delimiter `---a2ui_JSON---` MUST be placed on a brand new line by itself, with a blank line before and after it.
3. The first part is your conversational text response. Keep it brief and professional.
4. The second part is a single, raw JSON array of A2UI messages.
5. The JSON array MUST start on a new line immediately following the delimiter.
6. Do NOT wrap the A2UI JSON in markdown code fences (like ```json ... ```). It must be raw, valid JSON.
7. The JSON part MUST validate against the A2UI JSON SCHEMA provided below.

--- A2UI TEMPLATE RULES ---

- Use a `Column` component as the root.
- Inside the column, include the stepper `Text` elements (recapping the completed phases), a divider string using hyphens inside a `Text` component, a dashboard header `Text` component, and individual `Text` components for each deliverable (containing direct, clickable HTTPS links to the created Google Doc and Jira Task).
- Do NOT use `Card`, `Row`, `Button`, `List`, `Divider`, or `Icon` components, as they are unsupported in this client environment; use standard `Column` and `Text` components ONLY.
- Component IDs must be unique strings.
- Always end with `dataModelUpdate` and `beginRendering` messages.

--- A2UI WORKFLOW EXAMPLE ---

{ORCHESTRATOR_A2UI_EXAMPLE}

---BEGIN A2UI JSON SCHEMA---

{A2UI_SCHEMA}

---END A2UI JSON SCHEMA---
"""


root_agent = LlmAgent(
    name="Orchestrator_Agent",
    model=shared_model,
    description=(
        "Intuit PM Orchestrator. Coordinates the full Product Lifecycle for "
        "QuickBooks Tax Optimization, from regulatory research to dev handoff."
    ),
    instruction=f"{system_prompt}\n\n{system_instructions}" + _A2UI_INSTRUCTIONS,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=8192,
    ),
    tools=[
        query_regulatory_research_agent,
        query_tt_coordinator,
        validate_compliance,
        handoff_to_dev,
    ],
)

# Enable resumability only in deployed environments (Cloud Run sets the PORT env var).
_is_deployed = bool(os.environ.get("K_SERVICE"))

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(enabled=_is_deployed),
)
