#!/bin/bash

# Start LLM Router frontend (React + Vite)

set -e

# Go to project root
cd "$(dirname "$0")"

echo "🎨 Starting LLM Router Frontend..."
echo "UI will be available at http://localhost:5173"
echo ""
echo "Make sure the backend is running separately with: ./start_backend.sh"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run frontend dev server
cd webapp/frontend
npm run dev
