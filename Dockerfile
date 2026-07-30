# Use official slim Python image
FROM python:3.10-slim

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install FFmpeg for video/audio merging and clean up apt cache to save space
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Start Uvicorn, binding to 0.0.0.0 and the dynamically assigned PORT
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
