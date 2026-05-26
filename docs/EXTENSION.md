# Chrome Extension

## Install (dev mode — for hackathon demo)

1. Open `chrome://extensions`
2. Toggle **Developer mode** ON (top right)
3. Click **Load unpacked**
4. Select the `extension/` folder
5. Pin AgenticWeb to toolbar (puzzle icon)

## Usage

**Toolbar icon** → popup with quick goal input
**"Open full sidebar"** → side panel that stays open while browsing

The sidebar shows:
- Current page context (what site you're on)
- Live agent log as it works
- Final result

## How it connects

Extension calls `http://localhost:8765/run` directly (SSE stream).
Agent server must be running (`./scripts/start.sh`).

## After code changes

Go to `chrome://extensions` → click ↻ reload on AgenticWeb card.
