"""
日志查看 API — 读取 news-web.log 供前端实时查看。
"""
import os, re
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/logs", tags=["logs"])

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'news-web.log')


def _ensure_log_exists():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write('')


@router.get("")
def get_logs(
    lines: int = Query(200, ge=10, le=2000),
    level: str = Query('', description='过滤级别: DEBUG/INFO/WARNING/ERROR'),
    search: str = Query('', description='关键词搜索'),
):
    """获取最近 N 行日志，支持按级别过滤和关键词搜索。"""
    _ensure_log_exists()
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
    except Exception:
        return {'lines': [], 'total': 0, 'file': LOG_FILE}

    # 取最后 N 行
    recent = all_lines[-lines:]

    # 过滤
    result = []
    for line in recent:
        if level and level.upper() not in line.upper():
            continue
        if search and search.lower() not in line.lower():
            continue
        result.append(line.rstrip('\n'))

    return {
        'lines': result,
        'total': len(all_lines),
        'shown': len(result),
        'file': LOG_FILE,
    }


@router.get("/stream")
def get_log_tail(lines: int = Query(50, ge=10, le=500)):
    """获取最新日志（尾部），用于实时监控。"""
    _ensure_log_exists()
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
    except Exception:
        return {'lines': [], 'total': 0}

    recent = all_lines[-lines:]
    return {
        'lines': [l.rstrip('\n') for l in recent],
        'total': len(all_lines),
    }


@router.delete("/clear")
def clear_log():
    """清空日志文件。"""
    _ensure_log_exists()
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write('')
    return {'ok': True}
