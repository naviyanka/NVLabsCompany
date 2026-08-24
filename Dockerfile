FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir .

# Copy source
COPY src/ ./src/
COPY alembic/ ./alembic/ 2>/dev/null || true
COPY alembic.ini ./alembic.ini 2>/dev/null || true

# Set Python path
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "8000"]
