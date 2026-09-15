# Use official slim Python 3.11 image
FROM python:3.11-slim

# Prevent Python from writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production
ENV HEADLESS_MODE=true
ENV HOST=0.0.0.0
ENV PORT=7860
ENV HOME=/home/user
ENV HF_HOME=/home/user/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/user/.cache/huggingface
ENV TORCH_HOME=/home/user/.cache/torch

# Install system dependencies needed for Playwright and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (UID 1000 is standard and required for Hugging Face Spaces)
RUN useradd -m -u 1000 user

WORKDIR /app

# Ensure application and user directories exist with proper write permissions for user 1000
RUN mkdir -p /home/user/.cache /app/data/browser_profile /app/data/screenshots && \
    chown -R user:user /home/user /app

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and OS dependencies
RUN playwright install --with-deps chromium

# Pre-cache Sentence Transformer model weights as user 1000 into /home/user/.cache
USER user
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Switch back to root to copy application files and set ownership
USER root
COPY . .
RUN chown -R user:user /app /home/user

# Switch to non-root user for final container execution
USER user

# Expose standard HF Space port
EXPOSE 7860

# Run Uvicorn ASGI production server
CMD ["sh", "-c", "uvicorn src.server.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
