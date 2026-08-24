#!/usr/bin/env bash
# Anyq - start the whole stack locally (no Docker).
#
#   ./start.sh          start everything, stream status, Ctrl-C stops all
#
# Services: MongoDB (brew service) + backend :8000 + agent + frontend :3000
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
MEDIA_DIR="$ROOT/agent/manim-mcp-server/src/media/outputs"
mkdir -p "$LOG_DIR" "$MEDIA_DIR"

# ---------- config ----------
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and add GEMINI_API_KEY." >&2
  exit 1
fi
set -a; . ./.env; set +a

# Manim shells out to `latex`/`dvisvgm`; BasicTeX lives here and is not on the
# default PATH for non-login shells.
export PATH="/Library/TeX/texbin:$PATH"

: "${MONGO_URL:=mongodb://127.0.0.1:27017}"
: "${DATABASE_NAME:=anyq_db}"
export MONGO_URL DATABASE_NAME MEDIA_DIR

PIDS=()
cleanup() {
  echo ""
  echo "stopping services..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "stopped. (MongoDB left running - 'brew services stop mongodb-community' to stop it too)"
}
trap cleanup INT TERM EXIT

# ---------- 1. MongoDB ----------
if mongosh --quiet --eval 'db.adminCommand("ping")' >/dev/null 2>&1; then
  echo "mongodb   : already running"
else
  echo "mongodb   : starting..."
  brew services start mongodb-community >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    mongosh --quiet --eval 'db.adminCommand("ping")' >/dev/null 2>&1 && break
    sleep 1
  done
  echo "mongodb   : up"
fi

# ---------- 2. Backend ----------
echo "backend   : starting on :8000..."
(
  cd "$ROOT/backend"
  exec ./.venv/bin/uvicorn main:app \
    --host 127.0.0.1 --port 8000 \
    --ws-ping-interval 600 --ws-ping-timeout 600 --timeout-keep-alive 600
) > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -sf -m 2 http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 1
done
curl -sf -m 2 http://127.0.0.1:8000/health >/dev/null 2>&1 \
  && echo "backend   : healthy" \
  || { echo "backend   : FAILED - see $LOG_DIR/backend.log" >&2; exit 1; }

# ---------- 3. Agent ----------
echo "agent     : starting..."
(
  cd "$ROOT/agent"
  exec ./.venv/bin/python -u agent_ws_client.py
) > "$LOG_DIR/agent.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -s -m 2 http://127.0.0.1:8000/health 2>/dev/null | grep -q '"agent":"connected"' && break
  sleep 1
done
curl -s -m 2 http://127.0.0.1:8000/health 2>/dev/null | grep -q '"agent":"connected"' \
  && echo "agent     : connected" \
  || echo "agent     : WARNING not connected - see $LOG_DIR/agent.log"

# ---------- 4. Frontend ----------
echo "frontend  : starting on :3000..."
(
  cd "$ROOT/frontend"
  exec npm run dev
) > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -sf -m 2 -o /dev/null http://127.0.0.1:3000/ && break
  sleep 1
done

echo ""
echo "======================================================"
echo "  Anyq is running"
echo ""
echo "  open      http://localhost:3000"
echo "  login     admin / yesko"
echo ""
echo "  model     ${GEMINI_MODEL:-<unset>}"
echo "  database  ${DATABASE_NAME}"
echo "  logs      $LOG_DIR/{backend,agent,frontend}.log"
echo ""
echo "  Ctrl-C to stop"
echo "======================================================"

wait
