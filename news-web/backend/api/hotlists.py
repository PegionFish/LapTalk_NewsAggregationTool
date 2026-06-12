"""
实时热点 API — 微博热搜/知乎热榜/抖音热榜/头条热榜/B站热门视频
独立于文章检索，不经过内容缓存管道。
"""
import time
import threading
from fastapi import APIRouter, HTTPException, Query
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/hotlists", tags=["hotlists"])

PLATFORMS = ["weibo", "zhihu", "douyin", "toutiao", "bilibili"]


def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)


@router.get("")
def get_hotlists(
    date: str = Query("", description="日期 YYYY-MM-DD，默认今天"),
    platform: str = Query("", description="筛选平台，逗号分隔。如 weibo,zhihu。默认全部"),
):
    """获取各平台实时热点数据，按平台分组返回。"""
    db = get_db()
    platforms = None
    if platform:
        platforms = [p.strip() for p in platform.split(",") if p.strip() in PLATFORMS]
    return db.get_hotlists(date=date, platforms=platforms)


@router.get("/summary")
def get_hotlists_summary(date: str = Query("", description="日期 YYYY-MM-DD")):
    """获取热榜汇总统计（各平台条目数）。"""
    db = get_db()
    data = db.get_hotlists(date=date)
    return {
        "date": date or "today",
        "platforms": {pid: info["count"] for pid, info in data.items()},
        "total": sum(info["count"] for info in data.values()),
    }


@router.get("/top")
def get_hotlists_top(
    limit: int = Query(50, description="返回条数上限"),
    date: str = Query("", description="日期"),
):
    """获取跨平台热度 Top N（按排名合并，bilibili 按播放量排序）。"""
    db = get_db()
    data = db.get_hotlists(date=date)
    merged = []
    for pid, info in data.items():
        for item in info["items"]:
            merged.append({**item, "platform": pid})
    def sort_key(x):
        has_rank = 1 if x["rank"] and x["rank"] > 0 else 0
        return (-has_rank, x["rank"] if x["rank"] else 9999)
    merged.sort(key=sort_key)
    return {"total": len(merged), "items": merged[:limit]}


# ── 实时抓取状态 ─────────────────────────────────────────
_live_fetch_state = {"running": False, "done": False, "data": None, "error": ""}


def _do_live_fetch():
    """后台线程：实时抓取所有平台热点。"""
    global _live_fetch_state
    _live_fetch_state = {"running": True, "done": False, "data": None, "error": ""}
    try:
        from pipeline.fetch_platform_hotlists import (
            fetch_weibo, fetch_zhihu, fetch_douyin, fetch_toutiao, fetch_bilibili,
        )
        fetchers = [
            ("weibo", fetch_weibo),
            ("zhihu", fetch_zhihu),
            ("douyin", fetch_douyin),
            ("toutiao", fetch_toutiao),
            ("bilibili", fetch_bilibili),
        ]
        result = {}
        for pid, fetcher in fetchers:
            try:
                items = fetcher()
                result[pid] = {"count": len(items), "items": items}
            except Exception as e:
                result[pid] = {"count": 0, "items": [], "error": str(e)}
            time.sleep(0.3)
        _live_fetch_state["data"] = result
    except Exception as e:
        _live_fetch_state["error"] = str(e)
    finally:
        _live_fetch_state["running"] = False
        _live_fetch_state["done"] = True


@router.get("/live")
def get_hotlists_live():
    """实时抓取各平台热点 — 不走数据库，现场抓现场看。"""
    if _live_fetch_state.get("running"):
        return {"status": "running", "data": None}
    if _live_fetch_state.get("done") and _live_fetch_state.get("data"):
        return {"status": "done", "data": _live_fetch_state["data"]}
    return {"status": "idle", "data": None}


@router.post("/live/fetch")
def start_live_fetch():
    """启动实时抓取。"""
    if _live_fetch_state.get("running"):
        return {"ok": False, "message": "抓取正在进行中"}
    _live_fetch_state["done"] = False
    _live_fetch_state["data"] = None
    _live_fetch_state["error"] = ""
    threading.Thread(target=_do_live_fetch, daemon=True).start()
    return {"ok": True, "message": "开始实时抓取"}
