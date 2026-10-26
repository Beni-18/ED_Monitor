#!/bin/bash
# Local development launcher. Reads GROQ_API_KEY / SECRET_KEY from backend/.env.
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Stop any existing processes on 8000/3000
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

if [ ! -f "$ROOT/backend/.env" ]; then
  echo "backend/.env not found. Create it with SECRET_KEY=... and GROQ_API_KEY=..." >&2
  exit 1
fi

echo "Starting Backend..."
cd "$ROOT/backend" || exit 1
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Starting Frontend..."
cd "$ROOT/frontend" || exit 1
[ -d .next ] || npm run build
npm run start &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null' EXIT INT TERM
wait
