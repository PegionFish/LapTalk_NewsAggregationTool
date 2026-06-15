FROM dockerpull.org/library/python:3.11-slim

LABEL maintainer="LapTalk"
LABEL description="LapTalk News Aggregation Center"

# TUNA apt mirror for Chinese network
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Work dir
WORKDIR /app

# Python deps — TUNA PyPI mirror
COPY news-web/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r /tmp/requirements.txt && \
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
