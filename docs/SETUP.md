# Setup Guide

## Prerequisites

| Tool | Version | Get it |
|---|---|---|
| Python | 3.10+ | python.org |
| Node.js | 18+ | nodejs.org |
| Chrome | Any | google.com/chrome |

## Step 1 — API Key (free)

Get a free Gemini key at https://aistudio.google.com/apikey — no credit card needed.

## Step 2 — Configure

```bash
cp .env.example .env
# Open .env and paste your key:
# GEMINI_API_KEY=AIza...
```

## Step 3 — Start

```bash
chmod +x scripts/*.sh
./scripts/start.sh
```

First run installs Python deps + Playwright Chromium (~2 min).

## Step 4 — Use

- **Web:** open http://localhost:3000
- **Extension:** chrome://extensions → Developer mode → Load unpacked → select `extension/`
- **Telegram:** see docs/TELEGRAM.md

## Verify

```bash
curl http://localhost:8765/health
# Should return {"status":"ok","providers":{"available":["gemini"],...}}

curl -N -X POST http://localhost:8765/run \
  -H "Content-Type: application/json" \
  -d '{"goal":"what is 1+1"}'
# Should stream SSE events ending with {"type":"done","result":"2"}
```

## Troubleshooting

**Port already in use:**
```bash
./scripts/stop.sh && ./scripts/start.sh
```

**Playwright not found:**
```bash
cd agent && source .venv/bin/activate && playwright install chromium --with-deps
```

**No providers available:**
Check `.env` has at least one API key set (not empty).
