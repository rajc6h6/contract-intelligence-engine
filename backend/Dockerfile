FROM python:3.11-slim

WORKDIR /app

# Install system deps for asyncpg + psycopg binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pip tools
RUN pip install --no-cache-dir hatchling

# Copy project metadata first (layer cache)
COPY pyproject.toml .
COPY README.md* ./

# Install production dependencies
RUN pip install --no-cache-dir -e "."

# Copy source
COPY app/ ./app/
COPY mcp_server/ ./mcp_server/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

EXPOSE 8000 8001
