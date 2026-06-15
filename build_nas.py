#!/usr/bin/env python3
"""
Build full deployment package for QNAP NAS.
Creates a self-contained archive with everything needed for fresh install.
"""
import os, sys, json, tarfile, shutil, subprocess
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / 'news-web' / 'backend'
FRONTEND_DIR = ROOT / 'news-web' / 'frontend'
DIST_DIR = FRONTEND_DIR / 'dist'
VERSION_FILE = ROOT / 'VERSION'
OUTPUT_DIR = ROOT / 'dist'


def get_version():
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return '1.0.0'


def build_frontend():
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    print("  Building frontend...")
    subprocess.run(['npm', 'run', 'build'], cwd=str(FRONTEND_DIR), check=True, capture_output=True)
    if not (DIST_DIR / 'index.html').exists():
        raise RuntimeError("Frontend build failed")
    print("  Frontend OK")


def collect_backend():
    files = []
    skip_dirs = {'__pycache__', 'data', 'hot_reports'}
    skip_ext = {'.pyc', '.pyo'}
    for root, dirs, filenames in os.walk(str(BACKEND_DIR)):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in filenames:
            if any(f.endswith(ext) for ext in skip_ext):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, str(BACKEND_DIR))
            files.append(rel)
    return sorted(files)


def create_nas_scripts(version):
    """Create QNAP-friendly start/stop scripts."""

    start_script = f"""#!/bin/bash
# LapTalk News Aggregation — Start Script for QNAP NAS
# Usage: bash start.sh [port]

set -e

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/news-web/backend"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/pids/backend.pid"
PORT="${{1:-8081}}"

mkdir -p "$LOG_DIR" "$SCRIPT_DIR/pids"

# Check Python
PYTHON=""
for p in python3 python python3.11 python3.10 python3.9; do
    if command -v "$p" &>/dev/null; then
        PYTHON="$p"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "[ERR] Python not found. Install: opkg install python3"
    exit 1
fi
echo "[INFO] Python: $($PYTHON --version 2>&1)"

# Install dependencies
if [ -f "$BACKEND_DIR/requirements.txt" ]; then
    echo "[INFO] Installing Python dependencies..."
    cd "$BACKEND_DIR"
    "$PYTHON" -m pip install -r requirements.txt -q --break-system-packages 2>/dev/null || \\
    "$PYTHON" -m pip install -r requirements.txt -q 2>/dev/null || \\
    echo "[WARN] Some dependencies may be missing"
fi

# Stop existing instance
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
    rm -f "$PID_FILE"
fi

# Start
echo "[INFO] Starting LapTalk on port $PORT..."
cd "$BACKEND_DIR"
nohup "$PYTHON" main.py >> "$LOG_DIR/backend.log" 2>&1 &
echo "$!" > "$PID_FILE"
echo "[INFO] Started (PID: $!)"

# Wait for ready
for i in $(seq 1 30); do
    sleep 1
    if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
        echo "[OK] LapTalk is ready at http://localhost:$PORT"
        exit 0
    fi
done
echo "[WARN] Server may still be starting. Check: tail -f $LOG_DIR/backend.log"
"""

    stop_script = """#!/bin/bash
# LapTalk News Aggregation — Stop Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/pids/backend.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "[INFO] Stopping LapTalk (PID: $PID)..."
    kill "$PID" 2>/dev/null || true
    sleep 2
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "[OK] Stopped"
else
    echo "[INFO] LapTalk is not running"
fi
"""

    status_script = """#!/bin/bash
# LapTalk News Aggregation — Status Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/pids/backend.pid"
PORT="${1:-8081}"

echo ""
echo "=== LapTalk Status ==="

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "  Process:  running (PID: $(cat "$PID_FILE"))"
else
    echo "  Process:  stopped"
fi

if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    echo "  HTTP:     accessible on port $PORT"
    echo "  URL:      http://localhost:$PORT"
else
    echo "  HTTP:     not accessible"
fi

# DB stats
DB="$SCRIPT_DIR/news-web/backend/data/news.db"
if [ -f "$DB" ]; then
    COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM articles" 2>/dev/null || echo "?")
    echo "  Articles: $COUNT"
else
    echo "  Database: not initialized"
fi
echo ""
"""

    return start_script, stop_script, status_script


def create_config_template():
    return json.dumps({
        "db_path": "",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "pipeline_schedule_enabled": True,
        "pipeline_cron_hours": [10, 17],
        "pipeline_cron_minutes": [0, 0],
        "translation_enabled": False,
        "translation_base_url": "https://api.siliconflow.cn/v1",
        "translation_api_key": "",
        "translation_model": "deepseek-ai/DeepSeek-V3-0324",
        "translation_target_lang": "zh-CN",
        "content_cache_path": "",
        "platform_hotlist_enabled": True,
        "bilibili_max_pages": 7,
        "proxy_enabled": False,
        "proxy_url": ""
    }, indent=2, ensure_ascii=False)


def create_readme(version):
    return f"""# LapTalk News Aggregation v{version}

## Quick Start (QNAP NAS)

1. Upload this package to your NAS
2. Extract: `tar xzf laptalk-v{version}.tar.gz -C /share/CACHEDEV1_DATA/`
3. Start: `cd /share/CACHEDEV1_DATA/laptalk && bash start.sh`
4. Open: `http://NAS_IP:8081`

## First Time Setup

1. Open `http://NAS_IP:8081/settings` (admin/admin)
2. Configure AI API key (DeepSeek/OpenAI)
3. Optional: Configure translation API

## Commands

```bash
bash start.sh [port]    # Start (default port 8081)
bash stop.sh            # Stop
bash status.sh          # Check status
```

## Files

```
laptalk/
├── news-web/
│   ├── backend/        # Python backend
│   └── frontend/dist/  # Web UI
├── start.sh
├── stop.sh
├── status.sh
└── config.json         # Edit this with your API keys
```

## Requirements

- Python 3.9+ (QNAP Container Station or Entware)
- pip packages: fastapi, uvicorn, openai, apscheduler, bcrypt, pyjwt
"""

def main():
    version = get_version()
    pkg_name = f"laptalk-v{version}"

    print(f"Building deployment package v{version}...")

    # Build frontend
    if not (DIST_DIR / 'index.html').exists():
        build_frontend()
    else:
        print("  Using existing frontend build")

    # Collect backend
    backend_files = collect_backend()
    print(f"  Backend: {len(backend_files)} files")

    # Create temp dir
    temp_dir = OUTPUT_DIR / pkg_name
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        # Copy backend
        backend_dest = temp_dir / 'news-web' / 'backend'
        backend_dest.mkdir(parents=True)
        for rel in backend_files:
            src = BACKEND_DIR / rel
            dst = backend_dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(str(src), str(dst))

        # Copy frontend
        frontend_dest = temp_dir / 'news-web' / 'frontend' / 'dist'
        if DIST_DIR.exists():
            shutil.copytree(str(DIST_DIR), str(frontend_dest))

        # Create scripts
        start_s, stop_s, status_s = create_nas_scripts(version)
        (temp_dir / 'start.sh').write_text(start_s, encoding='utf-8')
        (temp_dir / 'stop.sh').write_text(stop_s, encoding='utf-8')
        (temp_dir / 'status.sh').write_text(status_s, encoding='utf-8')

        # Config template
        (temp_dir / 'config.json').write_text(create_config_template(), encoding='utf-8')

        # README
        (temp_dir / 'README.md').write_text(create_readme(version), encoding='utf-8')

        # VERSION
        (temp_dir / 'VERSION').write_text(version, encoding='utf-8')

        # Package
        output_path = OUTPUT_DIR / f'{pkg_name}.tar.gz'
        with tarfile.open(str(output_path), 'w:gz') as tar:
            for item in temp_dir.rglob('*'):
                if item.is_file():
                    arcname = str(item.relative_to(OUTPUT_DIR))
                    tar.add(str(item), arcname=arcname)

        size = output_path.stat().st_size
        print(f"\n  Package:  {output_path}")
        print(f"  Size:     {size / 1024:.1f} KB")
        print(f"  Version:  v{version}")
        print(f"\n  Deploy: tar xzf {pkg_name}.tar.gz -C /share/CACHEDEV1_DATA/")
        print(f"  Start:  cd /share/CACHEDEV1_DATA/{pkg_name} && bash start.sh")

    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


if __name__ == '__main__':
    main()
