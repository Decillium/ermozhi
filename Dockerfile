# Dockerfile for Ermozhi - Azure Container Apps Deployment
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies (ca-certificates for HTTPS, ffmpeg for edge-tts if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/
COPY .env* ./

# Create directory for output audio files
RUN mkdir -p /tmp/output_audio output_audio

EXPOSE 8080

# Launch FastAPI with uvicorn listening on 0.0.0.0:$PORT
CMD sh -c "uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8080}"
