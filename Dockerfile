FROM python:3.12-slim

# Copy ultra-fast uv package manager binary
COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /uvx /bin/

# Set working directory
WORKDIR /workspace

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace \
    UV_SYSTEM_PYTHON=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies using uv (10x faster than standard pip)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Create non-root system user for security
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /home/appuser/.cache/fastembed && \
    chown -R appuser:appgroup /workspace /home/appuser/.cache

# Copy source code and tests with non-root ownership
COPY --chown=appuser:appgroup . /workspace

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check probe
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: run FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
