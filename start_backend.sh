#!/bin/bash

# Start LLM Router backend (FastAPI)

set -e

# Activate venv
source venv/bin/activate

# Go to project root
cd "$(dirname "$0")"

echo "🚀 Starting LLM Router Backend..."
echo "API will be available at http://localhost:8000"
echo "Health check: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run FastAPI backend
python webapp/main.py
