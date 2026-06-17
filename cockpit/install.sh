#!/bin/bash
# ════════════════════════════════════════════════════════════
# LapTalk Cockpit 插件 — 一键安装脚本
#
# 用法：
#   bash cockpit/install.sh                 # 自动推导项目路径
#   LAPTALK_HOME=/opt/LapTalk bash cockpit/install.sh
#   sudo -E bash cockpit/install.sh         # 如安装目标目录需要 root
#
# 安装位置：/usr/local/share/cockpit/laptalk/
# 卸载：     rm -rf /usr/local/share/cockpit/laptalk
# ════════════════════════════════════════════════════════════
set -euo pipefail

# ── 颜色 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "  ${BLUE}[INFO]${NC} $1"; }
ok()   { echo -e "  ${GREEN}[OK]${NC}   $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $1"; }
err()  { echo -e "  ${RED}[ERR]${NC}  $1"; }

# ── 路径推导 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAPTALK_HOME="${LAPTALK_HOME:-$(dirname "$SCRIPT_DIR")}"
DEST="/usr/local/share/cockpit/laptalk"

# ── 前置检查 ──
echo ""
echo -e "${BLUE}══ LapTalk Cockpit 插件安装 ══${NC}"
echo ""

# 1. LAPTALK_HOME 是否有效
if [ ! -f "$LAPTALK_HOME/start_platform.sh" ]; then
    err "未在 $LAPTALK_HOME 找到 start_platform.sh"
    err "请用环境变量指定项目根目录：LAPTALK_HOME=/path/to/project bash $0"
    exit 1
fi
[ -f "$LAPTALK_HOME/start_platform.sh" ] && ok "找到项目：$LAPTALK_HOME"

# 2. Cockpit 是否安装
if ! command -v cockpit-bridge &>/dev/null && [ ! -d /usr/share/cockpit ]; then
    warn "未检测到 Cockpit，建议先安装："
    echo "    Debian/Ubuntu: sudo apt install cockpit"
    echo "    RHEL/CentOS:   sudo dnf install cockpit"
    echo "    （仍继续安装插件文件，稍后自行装 Cockpit）"
else
    ok "Cockpit 已安装"
fi

# 3. 安装目标目录写权限
if [ ! -d /usr/local/share/cockpit ] && [ ! -w /usr/local/share ]; then
    err "无法创建 $DEST，请用 sudo 运行：sudo -E bash $0"
    exit 1
fi

# ── 安装 ──
info "创建目录 $DEST"
mkdir -p "$DEST"

SRC_FILES=(manifest.json index.html laptalk.js laptalk.css)
for f in "${SRC_FILES[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$f" ]; then
        err "缺失源文件 $SCRIPT_DIR/$f"
        exit 1
    fi
done

info "复制文件..."
for f in "${SRC_FILES[@]}"; do
    cp "$SCRIPT_DIR/$f" "$DEST/$f"
done

# ── 注入 LAPTALK_HOME 到 index.html ──
# 把所有 __LAPTALK_HOME__ 占位符替换为实际项目路径
info "注入项目路径 LAPTALK_HOME=$LAPTALK_HOME"
# 兼容 GNU sed 与 BSD sed（macOS）：先写到临时文件再覆盖
TMP_HTML="$(mktemp)"
sed "s|__LAPTALK_HOME__|$LAPTALK_HOME|g" "$DEST/index.html" > "$TMP_HTML"
mv "$TMP_HTML" "$DEST/index.html"

ok "已安装到 $DEST"

# ── 权限检查 / 修复 ──
echo ""
info "权限检查..."
# Cockpit 以登录用户身份执行 start_platform.sh，该用户需要对项目目录可读写
CURRENT_USER="$(id -un)"
PROJECT_OWNER="$(stat -c '%U' "$LAPTALK_HOME" 2>/dev/null || stat -f '%Su' "$LAPTALK_HOME" 2>/dev/null || echo '?')"
LOGS_DIR="$LAPTALK_HOME/logs"
PIDS_DIR="$LAPTALK_HOME/pids"

mkdir -p "$LOGS_DIR" "$PIDS_DIR"

if [ "$PROJECT_OWNER" != "$CURRENT_USER" ]; then
    warn "项目目录归属用户为 '$PROJECT_OWNER'，但 Cockpit 将以 '$CURRENT_USER' 身份执行"
    warn "若无法启动/写日志，请执行："
    echo "    sudo chown -R $CURRENT_USER:$CURRENT_USER $LAPTALK_HOME"
else
    ok "项目目录归属当前用户 '$CURRENT_USER'"
fi

# 日志文件可读
BACKEND_LOG="$LOGS_DIR/backend.log"
if [ ! -f "$BACKEND_LOG" ]; then
    touch "$BACKEND_LOG"
    ok "已创建空日志文件 $BACKEND_LOG"
elif [ ! -r "$BACKEND_LOG" ]; then
    warn "$BACKEND_LOG 不可读，请执行：chmod +r $BACKEND_LOG"
else
    ok "日志文件可读"
fi

# start_platform.sh 可执行
if [ ! -x "$LAPTALK_HOME/start_platform.sh" ]; then
    chmod +x "$LAPTALK_HOME/start_platform.sh" 2>/dev/null && ok "已为 start_platform.sh 添加执行权限" \
        || warn "$LAPTALK_HOME/start_platform.sh 不可执行，请执行：chmod +x $LAPTALK_HOME/start_platform.sh"
else
    ok "start_platform.sh 可执行"
fi

# ── 完成提示 ──
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  安装完成！${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "  插件位置:   ${BLUE}$DEST${NC}"
echo -e "  项目路径:   ${BLUE}$LAPTALK_HOME${NC}"
echo -e "  后端 API:   ${BLUE}http://localhost:8081${NC}"
echo ""
echo -e "  ${YELLOW}下一步：${NC}"
echo -e "    1. ${YELLOW}退出当前 Cockpit 会话并重新登录${NC}（Cockpit 重登后才会扫描新插件）"
echo "    2. 左侧菜单「工具」下出现「LapTalk 平台」"
echo "    3. 如修改了代码，浏览器按 Ctrl+Shift+R 强刷"
echo ""
echo -e "  ${YELLOW}首次使用：${NC}点击「启动」按钮即可拉起后端 + 看门狗"
echo -e "  ${YELLOW}卸载：${NC}rm -rf $DEST"
echo ""
