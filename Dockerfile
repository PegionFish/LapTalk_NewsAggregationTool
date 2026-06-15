FROM python:3.11-slim

LABEL maintainer="LapTalk"
LABEL description="LapTalk News Aggregation Center"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Work dir
WORKDIR /app

# Python deps first (cache layer)
COPY news-web/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Backend
COPY news-web/backend/ /app/news-web/backend/

# Frontend
COPY news-web/frontend/dist/ /app/news-web/frontend/dist/

# Config template
COPY config.docker.json /app/config.json

# Data volumes
RUN mkdir -p /app/data /app/logs /app/pids /app/backups
VOLUME ["/app/data", "/app/logs", "/app/backups"]

# Expose
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8081/api/health || exit 1

# Start
ENV PYTHONUNBUFFERED=1
ENV NEWS_WEB_TESTING=""

CMD ["python", "news-web/backend/main.py"]
