#!/bin/bash
# QNAP NAS 一键部署脚本
# 在 NAS 上运行: bash deploy-qnap.sh
#
# 前提: 已安装 Container Station (Docker)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo "1.0.0")
DATA_DIR="/share/CACHEDEV1_DATA/laptalk"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

# Check Docker
if ! command -v docker &>/dev/null; then
    err "Docker not found. Install Container Station from QNAP App Center."
fi
info "Docker found: $(docker --version)"

# Configure Docker daemon with TUNA mirror for Chinese network
DAEMON_JSON="/etc/docker/daemon.json"
if [ ! -f "$DAEMON_JSON" ] || ! grep -q "tuna.tsinghua.edu.cn" "$DAEMON_JSON" 2>/dev/null; then
    info "Configuring Docker daemon with TUNA mirrors..."
    mkdir -p /etc/docker
    cat > "$DAEMON_JSON" << 'EOF'
{
  "registry-mirrors": [
    "https://mirrors.tuna.tsinghua.edu.cn",
    "https://docker.m.daocloud.io"
  ]
}
EOF
    # Restart Docker daemon if possible
    if command -v systemctl &>/dev/null; then
        systemctl restart docker 2>/dev/null || true
    elif command -v synoservicectl &>/dev/null; then
        synoservicectl --restart pkgctl-Docker 2>/dev/null || true
    fi
    info "Docker mirrors configured. May need to restart Docker daemon."
fi

# Create data dir
mkdir -p "$DATA_DIR/data" "$DATA_DIR/logs" "$DATA_DIR/backups"

# Copy config if not exists
if [ ! -f "$DATA_DIR/config.json" ]; then
    cp "$SCRIPT_DIR/config.docker.json" "$DATA_DIR/config.json"
    warn "Created default config.json — edit it to add your API keys:"
    warn "  vi $DATA_DIR/config.json"
fi

# Build image
IMAGE="laptalk:v${VERSION}"
info "Building Docker image: $IMAGE ..."
docker build -t "$IMAGE" "$SCRIPT_DIR"

# Stop old container
if docker ps -a --format '{{.Names}}' | grep -q '^laptalk$'; then
    info "Stopping old container..."
    docker stop laptalk 2>/dev/null || true
    docker rm laptalk 2>/dev/null || true
fi

# Run
info "Starting container..."
docker run -d \
    --name laptalk \
    --restart unless-stopped \
    -p 8081:8081 \
    -v "$DATA_DIR/data:/app/data" \
    -v "$DATA_DIR/logs:/app/logs" \
    -v "$DATA_DIR/backups:/app/backups" \
    -v "$DATA_DIR/config.json:/app/config.json" \
    "$IMAGE"

# Wait for ready
info "Waiting for service..."
for i in $(seq 1 30); do
    sleep 1
    if curl -s http://localhost:8081/api/health >/dev/null 2>&1; then
        echo ""
        info "========================================="
        info "  LapTalk v${VERSION} is running!"
        info "  URL: http://$(hostname):8081"
        info "  Config: $DATA_DIR/config.json"
        info "========================================="
        exit 0
    fi
    printf "."
done
echo ""
warn "Service may still be starting. Check: docker logs laptalk"
