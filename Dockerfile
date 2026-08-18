FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source code
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Install the package
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "8000"]
