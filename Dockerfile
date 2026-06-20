# Build frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY webapp/frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit || npm install
COPY webapp/frontend .
RUN npm run build

# Build backend
FROM python:3.11-slim
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code and modules to app root
COPY webapp/main.py ./main.py
COPY simulator ./simulator
COPY router ./router

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./dist

# Set Python path for imports
ENV PYTHONPATH=/app

# Serve static files from backend
RUN pip install --no-cache-dir fastapi-static-files

EXPOSE 8080

ENV PORT=8080
CMD ["python", "main.py"]
