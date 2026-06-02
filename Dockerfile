FROM python:3.12-slim AS base
# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create an unprivileged runtime user with a stable uid/gid so mounted
# volumes can be prepared for the running process.
RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --create-home --home-dir /app appuser

# Copy application code
COPY . .

RUN mkdir -p /app/journal \
    && chown -R appuser:appuser /app

USER appuser

# Default command (can be overridden)
CMD ["python", "app.py"]
