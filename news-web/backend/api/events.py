from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/events", tags=["events"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_events(status: str = "", min_articles: int = Query(1, ge=1), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    db = get_db()
    with db._conn() as conn:
        clauses = ["1=1"]
        params = []
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        if min_articles > 1:
            clauses.append("e.article_count >= ?")
            params.append(min_articles)
        where = " AND ".join(clauses)
        offset = (page - 1) * limit
        count = conn.execute(f"SELECT COUNT(*) FROM events e WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count, e.status
            FROM events e WHERE {where}
            ORDER BY e.last_seen DESC LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    return {
        'events': [{'id': r[0], 'title': r[1], 'first_seen': r[2], 'last_seen': r[3], 'article_count': r[4], 'status': r[5]} for r in rows],
        'total': count, 'page': page, 'limit': limit
    }

@router.get("/{event_id}")
def get_event(event_id: int):
    db = get_db()
    return db.get_event_timeline(event_id)

class EventUpdate(BaseModel):
    title: Optional[str] = None
    priority_label: Optional[str] = None

@router.patch("/{event_id}")
def update_event(event_id: int, body: EventUpdate):
    db = get_db()
    with db._conn() as conn:
        if body.title:
            conn.execute("UPDATE events SET title=? WHERE id=?", (body.title, event_id))
        if body.priority_label:
            # Apply priority to all articles in this event
            article_ids = conn.execute(
                "SELECT article_id FROM article_events WHERE event_id=?", (event_id,)
            ).fetchall()
            for (aid,) in article_ids:
                db.record_feedback(aid, 'priority_label', body.priority_label)
        conn.commit()
    return {'ok': True}

class MergeEvents(BaseModel):
    target_event_id: int

@router.post("/{event_id}/merge")
def merge_events(event_id: int, body: MergeEvents):
    """Merge event_id INTO target_event_id. Moves all articles and updates dates."""
    db = get_db()
    if event_id == body.target_event_id:
        raise HTTPException(400, "cannot_merge_with_self")
    with db._conn() as conn:
        src = conn.execute("SELECT first_seen, last_seen, article_count FROM events WHERE id=?", (event_id,)).fetchone()
        tgt = conn.execute("SELECT first_seen, last_seen, article_count FROM events WHERE id=?", (body.target_event_id,)).fetchone()
        if not src or not tgt:
            raise HTTPException(404, "event_not_found")
        # Move articles
        conn.execute("""
            INSERT OR IGNORE INTO article_events (article_id, event_id)
            SELECT article_id, ? FROM article_events WHERE event_id=?
        """, (body.target_event_id, event_id))
        # Update target dates and recalculate article_count from actual rows
        conn.execute("""
            UPDATE events SET
                first_seen = CASE WHEN ? < first_seen THEN ? ELSE first_seen END,
                last_seen = CASE WHEN ? > last_seen THEN ? ELSE last_seen END
            WHERE id=?
        """, (src[0], src[0], src[1], src[1], body.target_event_id))
        # Re-count target articles (INSERT OR IGNORE may have skipped duplicates)
        tgt_count = conn.execute(
            "SELECT COUNT(*) FROM article_events WHERE event_id=?", (body.target_event_id,)
        ).fetchone()[0]
        conn.execute("UPDATE events SET article_count=? WHERE id=?", (tgt_count, body.target_event_id))
        # Delete source event
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.execute("DELETE FROM article_events WHERE event_id=?", (event_id,))
        conn.commit()
    return {'ok': True, 'merged_into': body.target_event_id}

class SplitEvent(BaseModel):
    article_ids: list[int]
    new_event_title: Optional[str] = None

@router.post("/{event_id}/split")
def split_event(event_id: int, body: SplitEvent):
    """Split articles out of an event into a new event."""
    db = get_db()
    with db._conn() as conn:
        if len(body.article_ids) < 1:
            raise HTTPException(400, "need_at_least_one_article")
        event = conn.execute("SELECT title, first_seen, last_seen FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "event_not_found")
        new_title = body.new_event_title or f"{event[0]} (split)"
        today = event[1]
        # Create new event
        cur = conn.execute(
            "INSERT INTO events (title, first_seen, last_seen, article_count) VALUES (?, ?, ?, ?)",
            (new_title, today, today, len(body.article_ids))
        )
        new_id = cur.lastrowid
        # Move articles
        for aid in body.article_ids:
            conn.execute("UPDATE article_events SET event_id=? WHERE article_id=? AND event_id=?",
                        (new_id, aid, event_id))
        # Update old event article count
        remaining = conn.execute("SELECT COUNT(*) FROM article_events WHERE event_id=?", (event_id,)).fetchone()[0]
        conn.execute("UPDATE events SET article_count=? WHERE id=?", (remaining, event_id))
        if remaining == 0:
            conn.execute("UPDATE events SET status='inactive' WHERE id=?", (event_id,))
        conn.commit()
    return {'ok': True, 'new_event_id': new_id}
