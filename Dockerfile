# Stage 1: build the React frontend (frontend/ -> frontend/dist)
FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: the Flask app, which serves the API and the built frontend
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Every pinned package ships a manylinux wheel, so no compiler or client
# libraries are needed (psycopg2-binary bundles libpq)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code (.dockerignore keeps node_modules, venvs and caches out)
COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist

# Port 5000 locally (docker compose); Render sets PORT
EXPOSE 5000

# Bring the schema to the latest migration (alembic upgrade head) and seed an
# empty database, then serve. gunicorn reads gunicorn.conf.py from /app.
CMD ["sh", "-c", "python init_db.py && exec gunicorn app.main:app"]
