FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock /app/backend/requirements.lock
COPY backend/pyproject.toml /app/backend/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/pip python -c "import pathlib, subprocess, sys, tomllib; p=tomllib.loads(pathlib.Path('backend/pyproject.toml').read_text())['project']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-c', 'backend/requirements.lock', 'setuptools>=77'] + p['dependencies'] + p['optional-dependencies']['voice'])"
COPY backend/app /app/backend/app
RUN pip install --no-deps --no-build-isolation ./backend \
    && useradd --create-home appuser
COPY data/starter_kit /app/data/starter_kit
COPY data/product_promoter /app/data/product_promoter
COPY data/security /app/data/security
USER appuser
EXPOSE 8000
CMD ["python", "-m", "app.main"]
