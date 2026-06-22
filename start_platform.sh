#!/bin/bash
# LapTalk 新闻知识聚合中心 — 启动 / 停止 / 测试 / 状态
# 用法: bash start_platform.sh [start|stop|restart|status|test|build]

set -e

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── 路径 ──
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/news-web/backend"
FRONTEND_DIR="$ROOT/news-web/frontend"
LOGS_DIR="$ROOT/logs"
PID_DIR="$ROOT/pids"

# ── 端口 ──
PORT="${PORT:-8081}"

# ── 日志 / PID ──
mkdir -p "$LOGS_DIR" "$PID_DIR"
BACKEND_LOG="$LOGS_DIR/backend.log"
BACKEND_PID="$PID_DIR/backend.pid"

# ── 日志函数 ──
info()  { echo -e "  ${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "  ${GREEN}[OK]${NC}   $1"; }
warn()  { echo -e "  ${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "  ${RED}[ERR]${NC}  $1"; }

# ── 工具函数 ──
py() {
    # 优先 python（Windows 下 python3 可能指向 Store 存根）
    if python --version >/dev/null 2>&1; then echo "python"
    elif python3 --version >/dev/null 2>&1; then echo "python3"
    else echo ""; fi
}

# git-bash /c/... → Windows C:/... 路径转换（sqlite 需要）
to_win_path() {
    local p="$1"
    if command -v cygpath &>/dev/null; then
        cygpath -w "$p" 2>/dev/null || echo "$p"
    else
        echo "$p"
    fi
}

is_port_in_use() {
    # 优先用 ss（Linux），回退 netstat（Windows/macOS）
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$1 "
    elif command -v netstat &>/dev/null; then
        # Linux netstat 用 LISTEN，Windows 用 LISTENING
        netstat -tlnp 2>/dev/null | grep -q ":$1 " || \
        netstat -ano 2>/dev/null | grep -q ":$1 .*LISTENING"
    else
        return 1
    fi
}

get_pid_by_port() {
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep ":$1 " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1
    elif command -v netstat &>/dev/null; then
        netstat -tlnp 2>/dev/null | grep ":$1 " | awk '{print $NF}' | sed 's/\/.*//' | head -1
    fi
}

# 检测是否为 systemd 管理
_has_systemd() {
    [ -f /etc/systemd/system/laptalk.service ] || [ -f "$HOME/.config/systemd/user/laptalk.service" ]
}

# ═══════════════════════════════════════════════════
# 构建
# ═══════════════════════════════════════════════════

build_frontend() {
    info "构建前端..."
    cd "$FRONTEND_DIR"
    npm install --silent 2>/dev/null || true
    npx tsc && npx vite build || { err "前端构建失败"; return 1; }
    ok "前端构建完成 $FRONTEND_DIR/dist"
}

# ═══════════════════════════════════════════════════
# 启 / 停
# ═══════════════════════════════════════════════════

start_backend() {
    # 优先走 systemd（支持自动重启 + journald 日志）
    if _has_systemd; then
        info "通过 systemd 启动后端..."
        sudo systemctl start laptalk 2>/dev/null || systemctl --user start laptalk 2>/dev/null || true
        for i in $(seq 1 15); do
            sleep 1
            if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
                ok "后端就绪 (systemd)"
                return 0
            fi
        done
        err "后端启动超时 — journalctl -u laptalk 查看日志"
        return 1
    fi

    # 回退：无 systemd 时直接启动进程
    if is_port_in_use "$PORT"; then
        local pid; pid=$(get_pid_by_port "$PORT")
        warn "端口 $PORT 已被进程 $pid 占用 — 后端可能已在运行"
        echo "$pid" > "$BACKEND_PID"
        return 0
    fi

    info "启动后端 http://localhost:$PORT ..."
    cd "$BACKEND_DIR"
    nohup "$(py)" main.py >> "$BACKEND_LOG" 2>&1 &
    echo "$!" > "$BACKEND_PID"

    for i in $(seq 1 20); do
        sleep 1
        if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
            ok "后端就绪 (PID: $(cat "$BACKEND_PID"))"
            return 0
        fi
    done
    err "后端启动超时 — 查看 $BACKEND_LOG"
    return 1
}

stop_backend() {
    # 优先走 systemd
    if _has_systemd; then
        info "通过 systemd 停止后端..."
        sudo systemctl stop laptalk 2>/dev/null || systemctl --user stop laptalk 2>/dev/null || true
        ok "后端已停止 (systemd)"
        return 0
    fi

    # 回退：手动杀进程
    local pid
    if [ -f "$BACKEND_PID" ]; then
        pid=$(cat "$BACKEND_PID")
    fi
    if [ -z "$pid" ]; then
        pid=$(get_pid_by_port "$PORT")
    fi
    if [ -z "$pid" ]; then
        info "后端未运行"
        return 0
    fi

    info "停止后端 (PID: $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        warn "未响应，强制终止..."
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$BACKEND_PID"
    ok "后端已停止"
}

# ═══════════════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════════════

status() {
    echo ""
    echo -e "${BLUE}══ LapTalk 服务状态 ══${NC}"
    echo ""

    # 后端
    if is_port_in_use "$PORT"; then
        local pid; pid=$(get_pid_by_port "$PORT")
        echo -e "  后端 API   ${GREEN}● 运行中${NC}  port:$PORT  pid:$pid"
    else
        echo -e "  后端 API   ${RED}● 未启动${NC}"
    fi

    # 数据库
    local db="$BACKEND_DIR/data/news.db"
    if [ -f "$db" ]; then
        "$(py)" -c "
import sqlite3
c = sqlite3.connect(r'$(to_win_path "$db")')
open(r'$(to_win_path "$LOGS_DIR/_count.txt")','w').write(
    str(c.execute('SELECT COUNT(*) FROM articles').fetchone()[0])
)
c.close()
" 2>/dev/null
        local a; a=$(cat "$LOGS_DIR/_count.txt" 2>/dev/null || echo "?")
        rm -f "$LOGS_DIR/_count.txt"
        echo -e "  数据库     ${GREEN}$a${NC} 篇文章"
    else
        echo -e "  数据库     ${YELLOW}未找到${NC}"
    fi

    # 前端构建
    if [ -f "$FRONTEND_DIR/dist/index.html" ]; then
        echo -e "  前端构建   ${GREEN}已就绪${NC}"
    else
        echo -e "  前端构建   ${YELLOW}未构建${NC} — bash $0 build"
    fi

    echo ""
    echo -e "  主页       ${GREEN}http://localhost:$PORT${NC}"
    echo -e "  API 文档   ${GREEN}http://localhost:$PORT/docs${NC}"
    echo -e "  日志       ${YELLOW}$BACKEND_LOG${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════

test_all() {
    echo -e "\n${BLUE}══ 后端测试 (pytest) ══${NC}"
    cd "$ROOT/news-web"
    "$(py)" -m pytest tests/backend/test_api.py -v --tb=short

    echo -e "\n${BLUE}══ 前端测试 (vitest) ══${NC}"
    cd "$FRONTEND_DIR"
    npm test
}

test_backend() {
    cd "$ROOT/news-web"
    "$(py)" -m pytest tests/backend/test_api.py -v --tb=short
}

# ═══════════════════════════════════════════════════
# 看门狗 — 每 30s 检查健康，挂了自动重启
# ═══════════════════════════════════════════════════

WATCHDOG_PID_FILE="$PID_DIR/watchdog.pid"

start_watchdog() {
    # systemd 自带 Restart=always，无需额外看门狗
    if _has_systemd; then
        info "systemd 已管理服务存活 (Restart=always)，跳过看门狗"
        return 0
    fi

    if [ -f "$WATCHDOG_PID_FILE" ] && kill -0 "$(cat "$WATCHDOG_PID_FILE")" 2>/dev/null; then
        info "看门狗已在运行 (PID: $(cat "$WATCHDOG_PID_FILE"))"
        return 0
    fi

    info "启动看门狗 (每 30s 轮询健康)..."
    (
        while true; do
            sleep 30
            if ! curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
                warn "后端无响应，正在重启..."
                cd "$BACKEND_DIR"
                nohup "$(py)" main.py >> "$BACKEND_LOG" 2>&1 &
                echo "$!" > "$BACKEND_PID"
                for i in $(seq 1 15); do
                    sleep 1
                    if curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
                        ok "后端已自动恢复 (PID: $(cat "$BACKEND_PID"))"
                        break
                    fi
                done
            fi
        done
    ) &
    echo "$!" > "$WATCHDOG_PID_FILE"
    ok "看门狗已启动 (PID: $(cat "$WATCHDOG_PID_FILE"))"
}

stop_watchdog() {
    # systemd 管理时无需停止看门狗（根本不会启动）
    if _has_systemd; then
        return 0
    fi
    if [ -f "$WATCHDOG_PID_FILE" ]; then
        local wpid; wpid=$(cat "$WATCHDOG_PID_FILE")
        kill "$wpid" 2>/dev/null && info "看门狗已停止" || true
        rm -f "$WATCHDOG_PID_FILE"
    fi
}

test_frontend() {
    cd "$FRONTEND_DIR"
    npm test
}

# ═══════════════════════════════════════════════════
# 帮助
# ═══════════════════════════════════════════════════

help() {
    echo -e "${BLUE}LapTalk 启动脚本${NC}"
    echo ""
    echo "用法: bash start_platform.sh <命令>"
    echo ""
    echo "命令:"
    echo "  start      启动后端 + 看门狗 (需前端已构建)"
    echo "  stop       停止后端 + 看门狗"
    echo "  restart    重启后端 + 看门狗"
    echo "  status     查看服务 / 数据库 / 前端状态"
    echo "  test       运行全部测试 (pytest + vitest)"
    echo "  test-backend  仅后端测试"
    echo "  test-frontend 仅前端测试"
    echo "  build      仅构建前端"
    echo "  watchdog   启动看门狗（后端挂了自动重启）"
    echo ""
    echo "环境变量:"
    echo "  PORT=8081  自定义后端端口"
    echo ""
    echo "示例:"
    echo "  bash start_platform.sh start"
    echo "  bash start_platform.sh test"
    echo "  PORT=9090 bash start_platform.sh start"
    echo ""
}

# ═══════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════

CMD="${1:-start}"
shift 2>/dev/null || true

case "$CMD" in
    start)
        # 无前端构建 → 自动构建
        if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
            warn "前端未构建，自动构建..."
            build_frontend || exit 1
        fi
        start_backend && start_watchdog
        status
        ;;
    stop)
        stop_watchdog
        stop_backend
        ;;
    restart)
        stop_watchdog
        stop_backend
        sleep 2
        if [ ! -f "$FRONTEND_DIR/dist/index.html" ]; then
            build_frontend || exit 1
        fi
        start_backend && start_watchdog
        status
        ;;
    status)
        status
        ;;
    test)
        test_all
        ;;
    test-backend)
        test_backend
        ;;
    test-frontend)
        test_frontend
        ;;
    build)
        build_frontend
        ;;
    watchdog)
        start_watchdog
        ;;
    help|--help|-h)
        help
        ;;
    *)
        err "未知命令: $CMD"
        help
        exit 1
        ;;
esac
