#!/bin/bash
set -e
cd "$(dirname "$0")/frontend" && npm ci && npm run build
cd "$(dirname "$0")/backend" && pip install -r requirements.txt
exec python -m uvicorn main:app --host 0.0.0.0 --port 8080
