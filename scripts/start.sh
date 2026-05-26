#!/bin/bash
# AgenticWeb — Start Script
# Starts: Agent server (:8765) + Gateway (:8000) + Web UI (:3000)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ -f .env ] && export $(grep -v '^#' .env | xargs)

echo ""
echo "🌐 AgenticWeb — Starting"
echo "─────────────────────────"

# Python check
python3 -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null || { echo "❌ Python 3.10+ required"; exit 1; }

# Create venv if needed
if [ ! -d agent/.venv ]; then
  echo "⚙  Creating Python venv..."
  python3 -m venv agent/.venv
  source agent/.venv/bin/activate
  pip install -r agent/requirements.txt -q --break-system-packages 2>/dev/null || pip install -r agent/requirements.txt -q
  playwright install chromium --with-deps
else
  source agent/.venv/bin/activate
fi

# Start agent server
echo "🤖 Agent server → :${AGENT_PORT:-8765}"
cd agent && python3 server.py &
AGENT_PID=$!
cd "$ROOT"

# Wait for agent
echo -n "   Waiting"
for i in {1..20}; do
  curl -s http://localhost:${AGENT_PORT:-8765}/health > /dev/null 2>&1 && echo " ✓" && break
  echo -n "."; sleep 1
done

# Start gateway
echo "🔌 Gateway → :${GATEWAY_PORT:-8000}"
cd gateway && python3 main.py &
GW_PID=$!
cd "$ROOT"
sleep 2

# Start web UI (if node available)
WEB_PID=""
if command -v node &>/dev/null; then
  if [ ! -d web/node_modules ]; then
    echo "⚙  Installing web dependencies..."
    cd web && npm install --silent && cd "$ROOT"
  fi
  echo "🖥  Web UI → http://localhost:3000"
  cd web && npm run dev -- --host &
  WEB_PID=$!
  cd "$ROOT"
else
  echo "⚠  Node not found — Web UI skipped. Install Node 18+ to enable."
fi

sleep 2
echo ""
echo "─────────────────────────────────────"
echo "✅ AgenticWeb running!"
echo ""
echo "  Web UI:       http://localhost:3000"
echo "  Gateway:      http://localhost:${GATEWAY_PORT:-8000}"
echo "  Agent API:    http://localhost:${AGENT_PORT:-8765}/health"
echo "  MCP tools:    http://localhost:${AGENT_PORT:-8765}/mcp-tools"
echo "  Extension:    Load extension/ in chrome://extensions"
if [ -n "${TELEGRAM_BOT_TOKEN}" ]; then
  echo "  Telegram:     Bot active (set webhook — see docs/TELEGRAM.md)"
else
  echo "  Telegram:     Add TELEGRAM_BOT_TOKEN to .env to enable"
fi
echo ""
echo "Press Ctrl+C to stop all."
echo "─────────────────────────────────────"

echo "$AGENT_PID $GW_PID $WEB_PID" > .pids

trap "echo ''; kill $AGENT_PID $GW_PID $WEB_PID 2>/dev/null; rm -f .pids; echo 'Stopped.'; exit 0" INT TERM
wait
