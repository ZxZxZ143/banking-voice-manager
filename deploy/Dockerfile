# One HTTPS origin for the dashboard, API, speech and WebSocket connections.
# Build context: repository root. Secrets are runtime environment variables only.
FROM node:24-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BACKEND_HOST=0.0.0.0 STATIC_FRONTEND_DIR=/app/frontend/dist \
    STARTER_KIT_PATH=/app/data/starter_kit \
    PRODUCT_CATALOG_PATH=/app/data/product_promoter/catalog.json \
    SECURITY_POLICY_PATH=/app/data/security/policy.json \
    EVENT_DB_PATH=/app/data/runtime/veyra_events.db
WORKDIR /app
COPY backend/requirements.lock backend/pyproject.toml /app/backend/
RUN python -c "import pathlib, subprocess, sys, tomllib; p=tomllib.loads(pathlib.Path('backend/pyproject.toml').read_text())['project']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '-c', 'backend/requirements.lock', 'setuptools>=77'] + p['dependencies'] + p['optional-dependencies']['voice'])"
COPY backend/app /app/backend/app
RUN pip install --no-cache-dir --no-deps --no-build-isolation ./backend \
    && useradd --create-home appuser \
    && mkdir -p /app/data/runtime \
    && chown appuser:appuser /app/data/runtime
COPY data/starter_kit /app/data/starter_kit
COPY data/product_promoter /app/data/product_promoter
COPY data/security /app/data/security
COPY --from=frontend /build/frontend/dist /app/frontend/dist
USER appuser
EXPOSE 8000
CMD ["python", "-m", "app.main"]
