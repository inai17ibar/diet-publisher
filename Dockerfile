FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY pyproject.toml README.md ./
COPY app/ ./app/

# Install Python dependencies
RUN pip install --no-cache-dir .

# Create writable runtime directories
RUN mkdir -p images /data

# Expose port
EXPOSE 8000

# Run the application
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
