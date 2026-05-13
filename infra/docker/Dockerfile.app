FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY apps/app ./apps/app
COPY packages ./packages

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Create data directories
RUN mkdir -p data/artifacts data/cache

EXPOSE 8000

CMD ["uvicorn", "apps.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
