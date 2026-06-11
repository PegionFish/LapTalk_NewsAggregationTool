"""
实时热点 API — 微博热搜/知乎热榜/抖音热榜/头条热榜/B站热门视频
独立于文章检索，不经过内容缓存管道。
"""
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
    # 合并所有平台条目，按 rank 排序（rank=0 排在末尾）
    merged = []
    for pid, info in data.items():
        for item in info["items"]:
            merged.append({**item, "platform": pid})
    # 排序：有排名的优先，同排名按热度值降序
    def sort_key(x):
        has_rank = 1 if x["rank"] and x["rank"] > 0 else 0
        return (-has_rank, x["rank"] if x["rank"] else 9999)
    merged.sort(key=sort_key)
    return {"total": len(merged), "items": merged[:limit]}
