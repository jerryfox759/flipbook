FROM python:3.11-slim

# Avoid writing .pyc files and buffer outputs for cleaner logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set production environment variables
ENV HOST=0.0.0.0
ENV PORT=5000

WORKDIR /app

# Install basic system build dependencies (often useful for Python libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and templates
COPY app.py scraper.py ./
COPY templates/ ./templates/

# Ensure downloads directory exists inside the container
RUN mkdir -p /app/downloads

# Expose application port
EXPOSE 5000

# Start the application using gunicorn with an extended timeout to allow PDF compilation
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "180", "app:app"]
