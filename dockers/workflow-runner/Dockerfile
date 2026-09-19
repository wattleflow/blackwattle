# Multi-platform Dockerfile for workflow runner (ARM Alpine + x86_64)
# Supports: linux/arm64, linux/arm/v7, linux/amd64
#
# Build args:
#   PYTHON_VERSION: 3.12 or 3.13 (default: 3.12)
#   BASE_IMAGE: alpine image with Python preinstalled
#
# Usage:
#   docker build --platform linux/arm64 -t wattleflow-runner:latest .
#   docker build --platform linux/amd64 -t wattleflow-runner:latest .

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-alpine AS base

# System dependencies for Alpine.
# pandas and other wheel builds may need build tools temporarily.
RUN apk add --no-cache \
    ca-certificates \
    curl \
    git \
    && apk add --no-cache --virtual .build-deps \
    build-base \
    linux-headers \
    python3-dev

# Create app directory
WORKDIR /app

# Copy wattleflow packages (assumes they are installed from PyPI or local dist/).
# For now, install from PyPI. Adjust if building from local source.
COPY dockers/workflow-runner/requirements-runner.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-runner.txt

# Remove build dependencies (reduce image size)
RUN apk del .build-deps

# Copy example workflow and config (must be in same directory for YAML discovery)
COPY examples/workflows/01_synthetic_data.py /app/
COPY examples/workflows/01_synthetic_data.yaml /app/

# Copy scheduler script (from dockers/workflow-runner/)
COPY dockers/workflow-runner/workflow-scheduler.py /app/

# Copy .env for dotenv variable interpolation in YAML
COPY dockers/workflow-runner/.env /app/

# Create directories for output and data
RUN mkdir -p /app/output /app/data

# Set environment variables (can be overridden by docker-compose)
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO
ENV PROMETHEUS_PUSHGATEWAY_URL=http://wf-pushgateway:9091
ENV LOCAL_STORAGE_READ_PATH=/app/data
ENV LOCAL_STORAGE_WRITE_PATH=/app/output

# Entry point: run scheduler (reads schedule config from 01_synthetic_data.yaml)
# If schedule.enabled=true in YAML, runs in background scheduler mode
# Otherwise, runs workflow once
ENTRYPOINT ["python", "/app/workflow-scheduler.py"]
CMD []
