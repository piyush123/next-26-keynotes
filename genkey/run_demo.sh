#!/bin/bash
# =============================================================================
# Intuit PM Demo: Arden Tax Shield — Local Launch Script
# =============================================================================

# 1. Configuration & Paths
export PATH="$HOME/.local/bin:$PATH"
PROJECT_ROOT="$(pwd)"
AGENT_DIR="$PROJECT_ROOT/fabric-unified-intelligence/agents/orchestrator"
PORT=8501

echo "🚀 Starting Intuit PM Demo: Arden Tax Shield..."

# 2. Check for uv installation
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install it first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 3. Prepare Environment Variables (.env)
cd "$AGENT_DIR" || exit
if [ ! -f .env ]; then
    echo "📄 Creating .env from sample..."
    cp .env.sample .env
fi

# 4. Enable Standalone/Mock Mode for Sub-Agents
# This allows the demo to run without deploying the full agent cluster.
echo "🛠️  Configuring Standalone/Mock Mode..."
sed -i 's/^MARKET_RESEARCH_AGENT_URL=.*/MARKET_RESEARCH_AGENT_URL=mock/' .env
sed -i 's/^BQ_DATA_AGENT_PROJECT=.*/BQ_DATA_AGENT_PROJECT=mock/' .env

# 5. Launch Agent Playground
echo "🌐 Launching Agent Playground on port $PORT..."
echo "💡 Cloudtop Users: Access via https://$PORT-dot-$USER.ext.google.com/"
echo ""

# Unset VIRTUAL_ENV to avoid conflicts with other project venvs
unset VIRTUAL_ENV

# Use agents-cli which is already installed in the user's environment
# We use --host 0.0.0.0 for Cloudtop proxy compatibility
agents-cli playground --port $PORT --host 0.0.0.0
