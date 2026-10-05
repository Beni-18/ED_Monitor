#!/bin/bash
# Stop any existing processes on 8000/3000
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

echo "Starting Backend..."
cd backend
source venv/bin/activate
export GROQ_API_KEY="dummy-key-for-local-test"
export SECRET_KEY="my-super-secret-jwt-key"
uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Starting Frontend..."
cd ../frontend
npm run start &
FRONTEND_PID=$!

wait
