#!/usr/bin/env python3
"""
LapTalk Update Package Builder — packages backend + frontend into uploadable .tar.gz

Usage:
  python build_update.py                    # default version
  python build_update.py --version 1.2.3    # explicit version
  python build_update.py --output /tmp      # output directory
"""
import os, sys, json, tarfile, hashlib, shutil, subprocess, argparse
from datetime import datetime
from pathlib import Path

# Windows console UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / 'news-web' / 'backend'
FRONTEND_DIR = ROOT / 'news-web' / 'frontend'
DIST_DIR = FRONTEND_DIR / 'dist'

# ── 版本文件 ──
VERSION_FILE = ROOT / 'VERSION'


def get_version(explicit: str = '') -> str:
    if explicit:
        return explicit
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return datetime.now().strftime('%Y.%m.%d')


def bump_version(version: str) -> str:
    """Patch 版本 +1"""
    parts = version.split('.')
    if len(parts) == 3:
        parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)


def build_frontend():
    """Build frontend."""
    dist = FRONTEND_DIR / 'dist'
    if dist.exists():
        shutil.rmtree(dist)
    print("  Building frontend...")
    subprocess.run(
        ['npm', 'run', 'build'],
        cwd=str(FRONTEND_DIR),
        check=True,
        capture_output=True,
    )
    if not (dist / 'index.html').exists():
        raise RuntimeError("Frontend build failed: dist/index.html not found")
    print("  Frontend build complete")


def collect_backend_files() -> list[str]:
    """收集需要打包的后端文件"""
    skip_patterns = {
        '__pycache__', '*.pyc', '*.pyo', '.git', 'data', 'hot_reports',
        'news.db', '*.db-journal', '*.db-wal', '*.db-shm',
    }
    files = []
    for root, dirs, filenames in os.walk(str(BACKEND_DIR)):
        # 跳过不需要的目录
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'data', 'hot_reports')]
        for f in filenames:
            if f.endswith(('.pyc', '.pyo')):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, str(BACKEND_DIR))
            files.append(rel)
    return sorted(files)


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def create_install_script(version: str) -> str:
    return f"""#!/bin/bash
# LapTalk 更新安装脚本 — 由 build_update.py 自动生成
# 用法: bash install.sh <项目根目录> <更新包路径>

set -e

ROOT="${{1:-.}}"
PACKAGE="${{2}}"
BACKEND_DIR="$ROOT/news-web/backend"
FRONTEND_DIR="$ROOT/news-web/frontend"
BACKUP_DIR="$ROOT/backups/update-$(date +%Y%m%d%H%M%S)"

RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m'

info()  {{ echo -e "  $GREEN[INFO]$NC $1"; }}
warn()  {{ echo -e "  $YELLOW[WARN]$NC $1"; }}
err()   {{ echo -e "  $RED[ERR]$NC $1"; }}

# 1. 备份
info "备份当前文件到 $BACKUP_DIR ..."
mkdir -p "$BACKUP_DIR/backend" "$BACKUP_DIR/frontend"
cp -r "$BACKEND_DIR"/*.py "$BACKUP_DIR/backend/" 2>/dev/null || true
cp -r "$BACKEND_DIR/api" "$BACKUP_DIR/backend/" 2>/dev/null || true
cp -r "$BACKEND_DIR/auth" "$BACKUP_DIR/backend/" 2>/dev/null || true
cp -r "$BACKEND_DIR/db" "$BACKUP_DIR/backend/" 2>/dev/null || true
cp -r "$BACKEND_DIR/pipeline" "$BACKUP_DIR/backend/" 2>/dev/null || true
cp -r "$BACKEND_DIR/utils" "$BACKUP_DIR/backend/" 2>/dev/null || true
if [ -d "$FRONTEND_DIR/dist" ]; then
    cp -r "$FRONTEND_DIR/dist" "$BACKUP_DIR/frontend/"
fi
info "备份完成: $BACKUP_DIR"

# 2. 解压更新包
TEMP_DIR=$(mktemp -d)
info "解压更新包到 $TEMP_DIR ..."
tar xzf "$PACKAGE" -C "$TEMP_DIR"
PKG_DIR=$(ls -d "$TEMP_DIR"/laptalk-update-* 2>/dev/null || echo "$TEMP_DIR")

# 3. 更新后端
info "更新后端文件..."
if [ -d "$PKG_DIR/backend" ]; then
    cp -r "$PKG_DIR/backend"/*.py "$BACKEND_DIR/" 2>/dev/null || true
    for subdir in api auth db pipeline utils; do
        if [ -d "$PKG_DIR/backend/$subdir" ]; then
            mkdir -p "$BACKEND_DIR/$subdir"
            cp -r "$PKG_DIR/backend/$subdir"/* "$BACKEND_DIR/$subdir/" 2>/dev/null || true
        fi
    done
fi

# 4. 更新前端
info "更新前端文件..."
if [ -d "$PKG_DIR/frontend/dist" ]; then
    rm -rf "$FRONTEND_DIR/dist"
    cp -r "$PKG_DIR/frontend/dist" "$FRONTEND_DIR/"
fi

# 5. 安装依赖（如有变更）
if [ -f "$PKG_DIR/backend/requirements.txt" ]; then
    info "安装 Python 依赖..."
    cd "$BACKEND_DIR"
    pip install -r requirements.txt -q 2>/dev/null || warn "部分依赖安装失败"
fi

# 6. 写入版本
info "版本: {version}"

# 7. 清理
rm -rf "$TEMP_DIR"

info "安装完成！请重启服务使更新生效。"
echo ""
echo "  备份位置: $BACKUP_DIR"
echo "  回滚方法: cp -r $BACKUP_DIR/backend/* $BACKEND_DIR/"
echo ""
"""


def create_restart_script() -> str:
    return """#!/bin/bash
# LapTalk 服务重启脚本
# 由更新系统调用，重启后端服务

ROOT="${1:-.}"
BACKEND_DIR="$ROOT/news-web/backend"
PID_DIR="$ROOT/pids"
PORT="${PORT:-8081}"

# 停止旧进程
if [ -f "$PID_DIR/backend.pid" ]; then
    OLD_PID=$(cat "$PID_DIR/backend.pid")
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
    kill -9 "$OLD_PID" 2>/dev/null || true
fi

# 也尝试通过端口查找
PID=$(netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $NF}' | head -1)
if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    sleep 2
fi

# 启动新进程
cd "$BACKEND_DIR"
nohup python main.py >> "$ROOT/logs/backend.log" 2>&1 &
echo "$!" > "$PID_DIR/backend.pid"

# 等待就绪
for i in $(seq 1 20); do
    sleep 1
    if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
        echo "服务重启完成"
        exit 0
    fi
done
echo "服务启动超时"
exit 1
"""


def build_update_package(version: str, output_dir: str):
    """Build update package."""
    print(f"Building update package v{version} ...")

    # 1. Build frontend
    if not (DIST_DIR / 'index.html').exists():
        build_frontend()
    else:
        print("  Using existing frontend build")

    # 2. Collect backend files
    backend_files = collect_backend_files()
    print(f"  Backend files: {len(backend_files)}")

    # 3. Create manifest
    manifest = {
        'version': version,
        'build_time': datetime.now().isoformat(timespec='seconds'),
        'python_version': sys.version.split()[0],
        'backend_files': backend_files,
        'frontend_files': [],
    }

    # Frontend file list
    if DIST_DIR.exists():
        for root, _, filenames in os.walk(str(DIST_DIR)):
            for f in filenames:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, str(DIST_DIR))
                manifest['frontend_files'].append(rel)

    # 4. Create temp directory
    pkg_name = f'laptalk-update-{version}'
    temp_dir = ROOT / 'dist' / pkg_name
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        # Copy backend files
        backend_dest = temp_dir / 'backend'
        backend_dest.mkdir()
        for rel in backend_files:
            src = BACKEND_DIR / rel
            dst = backend_dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(str(src), str(dst))

        # Copy frontend
        frontend_dest = temp_dir / 'frontend' / 'dist'
        if DIST_DIR.exists():
            shutil.copytree(str(DIST_DIR), str(frontend_dest))

        # Write scripts
        scripts_dir = temp_dir / 'scripts'
        scripts_dir.mkdir()
        (scripts_dir / 'install.sh').write_text(create_install_script(version), encoding='utf-8')
        (scripts_dir / 'restart.sh').write_text(create_restart_script(), encoding='utf-8')

        # Write manifest
        manifest_path = temp_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

        # 5. Package
        output_path = Path(output_dir) / f'{pkg_name}.tar.gz'
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(str(output_path), 'w:gz') as tar:
            for item in temp_dir.rglob('*'):
                if item.is_file():
                    arcname = str(item.relative_to(temp_dir.parent))
                    tar.add(str(item), arcname=arcname)

        # Package size and hash
        pkg_size = output_path.stat().st_size
        pkg_hash = file_hash(str(output_path))

        # Update VERSION file
        VERSION_FILE.write_text(version, encoding='utf-8')

        print(f"\n  Package:  {output_path}")
        print(f"  Size:     {pkg_size / 1024:.1f} KB")
        print(f"  Hash:     {pkg_hash}")
        print(f"  Version:  v{version}")
        return str(output_path), pkg_hash

    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description='Build LapTalk update package')
    parser.add_argument('--version', '-v', default='', help='Version (reads from VERSION file by default)')
    parser.add_argument('--output', '-o', default=str(ROOT / 'dist'), help='Output directory')
    parser.add_argument('--bump', action='store_true', help='Auto-increment patch version')
    args = parser.parse_args()

    version = get_version(args.version)
    if args.bump:
        version = bump_version(version)

    build_update_package(version, args.output)


if __name__ == '__main__':
    main()
