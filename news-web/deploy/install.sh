#!/bin/bash
# LapTalk systemd 服务安装脚本
# 用法: sudo bash install.sh [PORT]  (默认端口 8081)
#
# 可移植说明:
#   1. 将此 deploy/ 目录连同项目一起复制到目标 Linux 实例
#   2. 确保 Python 3.12+、Node.js 22+ 及 pip 依赖已安装
#   3. 运行 sudo bash install.sh 完成 systemd 服务注册
#   4. 服务文件生成路径仅依赖 $PROJECT_ROOT，无硬编码绝对路径

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/news-web/backend"
LOGS_DIR="$PROJECT_ROOT/logs"
DATA_DIR="$BACKEND_DIR/data"
PORT="${1:-8081}"
SERVICE_NAME="laptalk"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_SYSTEM_DIR="/etc/systemd/system"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "  ${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "  ${GREEN}[OK]${NC}   $1"; }
err()   { echo -e "  ${RED}[ERR]${NC}  $1"; }

echo ""
echo -e "${BLUE}══ LapTalk systemd 服务安装 ══${NC}"
echo ""
echo "  项目路径:  $PROJECT_ROOT"
echo "  后端目录:  $BACKEND_DIR"
echo "  端口:      $PORT"
echo ""

# ── 前置检查 ────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    err "未找到 python3 — 请先安装 Python 3.12+"
    exit 1
fi

if ! command -v systemctl &>/dev/null; then
    err "未找到 systemctl — 此脚本需要 systemd"
    exit 1
fi

# ── 创建必要目录 ────────────────────────────────────────
mkdir -p "$LOGS_DIR" "$DATA_DIR"

# ── 生成服务文件 (使用 PROJECT_ROOT 动态替换路径) ──────
TEMPLATE="$SCRIPT_DIR/laptalk.service.template"
if [ -f "$TEMPLATE" ]; then
    info "从模板生成服务文件..."
    sed -e "s|{{PROJECT_ROOT}}|$PROJECT_ROOT|g" \
        -e "s|{{PORT}}|$PORT|g" \
        -e "s|{{USER}}|$(whoami)|g" \
        "$TEMPLATE" > "$SCRIPT_DIR/$SERVICE_FILE"
    ok "已生成 $SERVICE_FILE"
fi

# ── 安装 ────────────────────────────────────────────────
if [ "$EUID" -eq 0 ] || [ -w "$SYSTEMD_SYSTEM_DIR" ]; then
    # 系统级安装
    info "安装为系统服务: $SYSTEMD_SYSTEM_DIR/$SERVICE_FILE"
    cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_SYSTEM_DIR/$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl start "$SERVICE_NAME"
else
    # 用户级安装
    info "安装为用户服务: $SYSTEMD_USER_DIR/$SERVICE_FILE"
    mkdir -p "$SYSTEMD_USER_DIR"
    cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_USER_DIR/$SERVICE_FILE"
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user start "$SERVICE_NAME"
    # 允许用户服务在未登录时运行
    loginctl enable-linger "$(whoami)" 2>/dev/null || true
fi

# ── 验证 ────────────────────────────────────────────────
sleep 3
if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
    ok "服务已启动，健康检查通过"
    echo ""
    echo "  主页:      http://localhost:$PORT"
    echo "  API 文档:  http://localhost:$PORT/docs"
    echo "  健康检查:  http://localhost:$PORT/api/health"
    echo ""
    echo "  管理命令:"
    echo "    systemctl status $SERVICE_NAME    # 查看状态"
    echo "    systemctl restart $SERVICE_NAME   # 重启服务"
    echo "    journalctl -u $SERVICE_NAME -f    # 查看日志"
    echo ""
else
    err "健康检查失败 — 检查日志: journalctl -u $SERVICE_NAME -n 30"
    exit 1
fi
