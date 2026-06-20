#!/bin/bash

# Start LLM Router (both backend and frontend)

set -e

# Go to project root
cd "$(dirname "$0")"

echo "🚀 Starting LLM Router (Backend + Frontend)..."
echo ""
echo "Backend API: http://localhost:8000"
echo "Frontend UI: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both services"
echo ""

# Start backend in background
./start_backend.sh &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend in foreground (so Ctrl+C works naturally)
trap "kill $BACKEND_PID" EXIT
./start_frontend.sh
