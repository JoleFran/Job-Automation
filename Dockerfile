FROM python:3.11-slim

# Install LibreOffice for PDF export + dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
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
# Templates are populated via Railway volume or by uploading via /generate
RUN mkdir -p /app/templates /app/outputs

# Railway sets $PORT dynamically — Gunicorn reads it via the CMD
EXPOSE 8000

# Use Gunicorn for production; 1 worker because LibreOffice is not thread-safe for PDF export
CMD ["/bin/sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
