# Production-Ready Dockerfile for RAG Knowledge Management System
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Copy requirements first for better caching
COPY --chown=app:app requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy application code
COPY --chown=app:app . .

# Create necessary directories
RUN mkdir -p uploads vector_db logs

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=main.py
ENV FLASK_ENV=production
ENV PATH="/home/app/.local/bin:${PATH}"

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]