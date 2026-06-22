"""
热搜/趋势 API — 查询 trending_items 表
trending_items 存储各平台热搜条目（微博/知乎/抖音/头条/B站等）
独立于新闻文章，不经过内容缓存管道。
"""

from fastapi import APIRouter, HTTPException, Query
import json
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/trending", tags=["trending"])


def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)


@router.get("")
def list_trending(
    platform: str = Query("", description="筛选平台，如 weibo/zhihu/douyin/toutiao/bilibili"),
    trend_type: str = Query("", description="筛选类型，如 hotlist/video"),
    date_from: str = Query("", description="起始日期 YYYY-MM-DD"),
    date_to: str = Query("", description="结束日期 YYYY-MM-DD"),
    q: str = Query("", description="搜索关键词"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """分页列出热搜/趋势条目，支持平台/类型/日期筛选。"""
    db = get_db()
    with db._conn() as conn:
        clauses: list[str] = ["1=1"]
        params: list = []
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if trend_type:
            clauses.append("trend_type = ?")
            params.append(trend_type)
        if date_from:
            clauses.append("fetched_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("fetched_at <= ?")
            params.append(date_to)
        if q:
            clauses.append("title LIKE ?")
            params.append(f"%{q}%")

        where = " AND ".join(clauses)
        offset = (page - 1) * limit

        count = conn.execute(
            f"SELECT COUNT(*) FROM trending_items WHERE {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT id, title, platform, trend_type, url, rank, heat_score,
                       video_desc, author, play_count, danmaku_count, cover_url,
                       fetched_at, published_date, metadata, text_content
                FROM trending_items WHERE {where}
                ORDER BY fetched_at DESC, rank ASC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    items = [
        {
            "id": r[0],
            "title": r[1],
            "platform": r[2],
            "trend_type": r[3],
            "url": r[4],
            "rank": r[5],
            "heat_score": r[6],
            "video_desc": r[7],
            "author": r[8],
            "play_count": r[9],
            "danmaku_count": r[10],
            "cover_url": r[11],
            "fetched_at": r[12],
            "published_date": r[13] or "",
            "metadata": json.loads(r[14]) if r[14] and r[14] != "{}" else {},
            "text_content": r[15] or "",
        }
        for r in rows
    ]

    return {"items": items, "total": count, "page": page, "limit": limit}


@router.get("/{item_id}")
def get_trending_item(item_id: int):
    """获取单条热搜/趋势详情。"""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            """SELECT id, title, platform, trend_type, url, rank, heat_score,
                      video_desc, author, play_count, danmaku_count, cover_url,
                      fetched_at, published_date, metadata, text_content
               FROM trending_items WHERE id=?""",
            (item_id,),
        ).fetchone()

    if not row:
        raise HTTPException(404, "trending_item_not_found")

    return {
        "id": row[0],
        "title": row[1],
        "platform": row[2],
        "trend_type": row[3],
        "url": row[4],
        "rank": row[5],
        "heat_score": row[6],
        "video_desc": row[7],
        "author": row[8],
        "play_count": row[9],
        "danmaku_count": row[10],
        "cover_url": row[11],
        "fetched_at": row[12],
        "published_date": row[13] or "",
        "metadata": json.loads(row[14]) if row[14] and row[14] != "{}" else {},
        "text_content": row[15] or "",
    }


@router.get("/platforms")
def list_platforms():
    """列出所有平台及其条目数。"""
    db = get_db()
    with db._conn() as conn:
        rows = conn.execute(
            """SELECT platform, trend_type, COUNT(*) as cnt
               FROM trending_items
               GROUP BY platform, trend_type
               ORDER BY platform, trend_type"""
        ).fetchall()

        platforms: dict = {}
        for r in rows:
            p = r[0]
            tt = r[1]
            cnt = r[2]
            if p not in platforms:
                platforms[p] = {"platform": p, "total": 0, "types": {}}
            platforms[p]["total"] += cnt
            platforms[p]["types"][tt] = cnt

        # 各平台最新抓取时间
        for p in platforms:
            time_row = conn.execute(
                "SELECT MAX(fetched_at) FROM trending_items WHERE platform=?",
                (p,),
            ).fetchone()
            platforms[p]["last_fetch"] = time_row[0] if time_row[0] else ""

    return {
        "platforms": sorted(
            platforms.values(), key=lambda x: x["total"], reverse=True
        )
    }
