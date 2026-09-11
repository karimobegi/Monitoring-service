FROM python:3.12-slim

# Unbuffered output so logs show up in `docker compose logs` immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first: this layer stays cached until the lock file changes
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

# Code last: editing app code only rebuilds from here down
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Default command; compose.yaml overrides it for worker, beat and migrate
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
