FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY generate_resume.py .

RUN mkdir -p /app/base_resumes /app/outputs

EXPOSE 8000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
