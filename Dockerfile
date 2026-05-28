FROM python:3.11-slim

# Minimal system deps — LibreOffice added back once service is stable
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY generate_resume.py .

# Create directories for templates and outputs
RUN mkdir -p /app/templates /app/outputs

EXPOSE 8000

CMD ["/bin/sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
