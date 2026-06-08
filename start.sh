#!/usr/bin/env bash
#
# Launch the SmartSplit web UI.
# Activates the venv, starts the FastAPI server and opens it in your browser.
#
# Examples:
#   ./start.sh                 # http://127.0.0.1:8000
#   PORT=9000 ./start.sh       # custom port
#   HOST=0.0.0.0 ./start.sh    # listen on all interfaces (local network)
#
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f venv/bin/activate ]; then
  echo "venv not found. Run first: python3 -m venv venv && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

# Check the web dependencies are installed.
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "Web dependencies missing. Installing from requirements.txt..."
  pip install -q -r requirements.txt
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
URL="http://${HOST}:${PORT}"

echo "Starting SmartSplit web UI -> $URL  (Ctrl-C to stop)"

# Open the browser shortly after the server comes up (best effort).
(
  sleep 1.5
  if command -v open >/dev/null 2>&1; then open "$URL"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" # Linux
  fi
) >/dev/null 2>&1 &

exec python3 -m smartsplit web --host "$HOST" --port "$PORT"
