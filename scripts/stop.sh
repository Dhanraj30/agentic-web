#!/bin/bash
cd "$(dirname "$0")/.."
if [ -f .pids ]; then
  read -r PIDS < .pids
  kill $PIDS 2>/dev/null && echo "✅ Stopped." || echo "Already stopped."
  rm -f .pids
else
  lsof -ti:8765,8000,3000 | xargs kill -9 2>/dev/null; echo "✅ Stopped."
fi
