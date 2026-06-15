#!/bin/bash
# Build Docker image and export as importable archive for QNAP Container Station
# Usage: bash build-docker-image.sh
#
# Output: dist/laptalk-v{version}.tar (importable container image)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo "1.0.0")
IMAGE_NAME="laptalk"
TAG="v${VERSION}"
OUTPUT="$SCRIPT_DIR/dist"

echo "=== Building LapTalk Docker Image ==="
echo "  Version: $TAG"

# Check Docker
if ! command -v docker &>/dev/null; then
    echo "[ERR] Docker not found. Install Docker first."
    exit 1
fi

# Ensure frontend is built
if [ ! -f "$SCRIPT_DIR/news-web/frontend/dist/index.html" ]; then
    echo "[INFO] Building frontend..."
    cd "$SCRIPT_DIR/news-web/frontend"
    npm install --silent 2>/dev/null || true
    npx tsc && npx vite build
    cd "$SCRIPT_DIR"
fi

# Build image
echo "[INFO] Building Docker image..."
docker build -t "$IMAGE_NAME:$TAG" "$SCRIPT_DIR"

# Export as tar
mkdir -p "$OUTPUT"
docker save "$IMAGE_NAME:$TAG" -o "$OUTPUT/${IMAGE_NAME}-${TAG}.tar"

SIZE=$(stat -f%z "$OUTPUT/${IMAGE_NAME}-${TAG}.tar" 2>/dev/null || stat -c%s "$OUTPUT/${IMAGE_NAME}-${TAG}.tar" 2>/dev/null || echo "?")

echo ""
echo "=== Done ==="
echo "  Image: $IMAGE_NAME:$TAG"
echo "  File:  $OUTPUT/${IMAGE_NAME}-${TAG}.tar ($(( SIZE / 1024 / 1024 )) MB)"
echo ""
echo "  Import to QNAP Container Station:"
echo "    1. Open Container Station"
echo "    2. Create → Import Image"
echo "    3. Select ${IMAGE_NAME}-${TAG}.tar"
echo "    4. Set port mapping: 8081 → 8081"
echo "    5. Mount volume: /share/CACHEDEV1_DATA/laptalk/data → /app/data"
echo "    6. Start"
echo ""
