# Build frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY webapp/frontend/package*.json ./
RUN npm ci
COPY webapp/frontend .
RUN npm run build

# Build backend
FROM python:3.11-slim
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY webapp/main.py .
COPY simulator ../simulator

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./dist

# Serve static files from backend
RUN pip install --no-cache-dir fastapi-static-files

EXPOSE 8080

ENV PORT=8080
CMD ["python", "main.py"]
