#!/usr/bin/env python3
"""
Build Docker image and export as importable .tar for QNAP Container Station.

Usage:
  python build_docker_image.py            # build + export
  python build_docker_image.py --push     # build + push to registry

Output: dist/laptalk-v{version}.tar
"""
import os, sys, subprocess, shutil, json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / 'VERSION'
DIST_DIR = ROOT / 'dist'
IMAGE_NAME = 'laptalk'


def get_version():
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return '1.0.0'


def run(cmd, **kwargs):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)
    if result.stdout:
        for line in result.stdout.strip().splitlines()[-5:]:
            print(f"    {line}")
    if result.returncode != 0:
        print(f"  [ERR] {result.stderr[:500]}")
        return False
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Build LapTalk Docker image')
    parser.add_argument('--push', action='store_true', help='Push to registry instead of export')
    parser.add_argument('--tag', default='', help='Custom tag')
    args = parser.parse_args()

    version = args.tag or f'v{get_version()}'
    tag = f'{IMAGE_NAME}:{version}'

    print(f"=== Build LapTalk Docker Image ({tag}) ===\n")

    # Check Docker
    if not run('docker --version'):
        print("\n[ERR] Docker not found. Install Docker Desktop for Windows.")
        print("      https://docs.docker.com/desktop/install/windows-install/")
        sys.exit(1)

    # Ensure frontend built
    dist = ROOT / 'news-web' / 'frontend' / 'dist'
    if not (dist / 'index.html').exists():
        print("[INFO] Building frontend...")
        subprocess.run(['npm', 'run', 'build'], cwd=str(ROOT / 'news-web' / 'frontend'), check=True)
    else:
        print("[INFO] Frontend already built\n")

    # Build image
    print("[1/2] Building Docker image...")
    if not run(f'docker build -t {tag} .', cwd=str(ROOT)):
        print("[ERR] Build failed")
        sys.exit(1)

    # Export or push
    if args.push:
        print(f"\n[2/2] Pushing to registry...")
        if not run(f'docker push {tag}'):
            print("[ERR] Push failed")
            sys.exit(1)
        print(f"\n[OK] Pushed: {tag}")
    else:
        DIST_DIR.mkdir(exist_ok=True)
        output = DIST_DIR / f'laptalk-{version}.tar'
        print(f"\n[2/2] Exporting image to {output.name}...")
        if not run(f'docker save {tag} -o {output}'):
            print("[ERR] Export failed")
            sys.exit(1)

        size_mb = output.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"  Image:  {tag}")
        print(f"  File:   {output} ({size_mb:.1f} MB)")
        print(f"{'='*50}")
        print(f"""
  QNAP Container Station 导入方法:
  ───────────────────────────────
  1. 打开 Container Station
  2. 创建 → 导入镜像 (Import Image)
  3. 选择文件: laptalk-{version}.tar
  4. 端口映射: 8081 → 8081
  5. 卷挂载:
     /share/CACHEDEV1_DATA/laptalk/data → /app/data
     /share/CACHEDEV1_DATA/laptalk/config.json → /app/config.json
  6. 启动容器
  7. 访问 http://NAS_IP:8081
""")


if __name__ == '__main__':
    main()
