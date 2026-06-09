from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/articles", tags=["articles"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_articles(
    q: str = "",
    source: str = "",
    date_from: str = "",
    date_to: str = "",
    priority: str = "",
    verified: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """Search articles with multi-dimensional filtering."""
    db = get_db()
    with db._conn() as conn:
        clauses = []
        params = []
        if q:
            clauses.append("(a.title LIKE ? OR a.keywords LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if source:
            clauses.append("a.source = ?")
            params.append(source)
        if date_from:
            clauses.append("a.fetched_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("a.fetched_at <= ?")
            params.append(date_to)
        if priority in ('high', 'medium', 'low'):
            clauses.append("a.priority_label = ?")
            params.append(priority)
        if verified == 'yes':
            clauses.append("a.human_verified != 0")
        elif verified == 'no':
            clauses.append("a.human_verified = 0")

        where = " AND ".join(clauses) if clauses else "1=1"
        offset = (page - 1) * limit

        count = conn.execute(f"SELECT COUNT(*) FROM articles a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags
            FROM articles a WHERE {where}
            ORDER BY a.fetched_at DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

    import json
    articles = [{
        'id': r[0], 'title': r[1], 'source': r[2], 'url': r[3],
        'published': r[4], 'fetched': r[5], 'score': r[6],
        'label': r[7], 'verified': r[8],
        'keywords': json.loads(r[9]) if r[9] else [],
        'human_tags': json.loads(r[10]) if r[10] else [],
    } for r in rows]

    return {'articles': articles, 'total': count, 'page': page, 'limit': limit}

@router.get("/{article_id}")
def get_article(article_id: int):
    db = get_db()
    with db._conn() as conn:
        row = conn.execute("""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags,
                   a.category, a.metadata
            FROM articles a WHERE a.id=?
        """, (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "article_not_found")
        # Find event membership
        evt = conn.execute("""
            SELECT e.id, e.title FROM events e
            JOIN article_events ae ON ae.event_id = e.id
            WHERE ae.article_id=?
        """, (article_id,)).fetchone()

    import json
    return {
        'id': row[0], 'title': row[1], 'source': row[2], 'url': row[3],
        'published': row[4], 'fetched': row[5], 'score': row[6],
        'label': row[7], 'verified': row[8],
        'keywords': json.loads(row[9]) if row[9] else [],
        'human_tags': json.loads(row[10]) if row[10] else [],
        'category': row[11], 'metadata': json.loads(row[12]) if row[12] else {},
        'event': {'id': evt[0], 'title': evt[1]} if evt else None,
    }

class ArticleUpdate(BaseModel):
    priority_label: Optional[str] = None
    human_tags: Optional[str] = None
    human_verified: Optional[int] = None

@router.patch("/{article_id}")
def update_article(article_id: int, body: ArticleUpdate):
    db = get_db()
    if body.priority_label:
        db.record_feedback(article_id, 'priority_label', body.priority_label)
    if body.human_tags:
        db.record_feedback(article_id, 'keywords', body.human_tags)
    if body.human_verified is not None:
        with db._conn() as conn:
            conn.execute("UPDATE articles SET human_verified=? WHERE id=?", (body.human_verified, article_id))
            conn.commit()
    return {'ok': True}

@router.get("/{article_id}/content")
async def proxy_article_content(article_id: int):
    """Proxy fetch the original article content, carrying the configured UA."""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute("SELECT url FROM articles WHERE id=?", (article_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "no_url")
    async with httpx.AsyncClient() as client:
        resp = await client.get(row[0], headers={'User-Agent': config.user_agent}, follow_redirects=True, timeout=15)
    return resp.text
