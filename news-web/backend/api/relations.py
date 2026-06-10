from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/relations", tags=["relations"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("/suggested")
def get_suggested_relations():
    """Get AI-suggested event relations pending human review."""
    db = get_db()
    return {'suggestions': db.get_pending_relations()}

@router.get("/between")
def get_relations_between(event_ids: str = Query(..., description="Comma-separated event IDs")):
    """Get all relations between a set of event IDs. Used to reconstruct edges on canvas."""
    db = get_db()
    try:
        ids = [int(x.strip()) for x in event_ids.split(',') if x.strip()]
    except ValueError:
        raise HTTPException(400, "invalid_event_ids")
    if not ids:
        return {'relations': []}

    placeholders = ','.join('?' * len(ids))
    with db._conn() as conn:
        rows = conn.execute(f"""
            SELECT er.id, er.from_event_id, er.to_event_id, er.relation,
                   e1.title AS from_title, e2.title AS to_title,
                   er.created_by
            FROM event_relations er
            JOIN events e1 ON e1.id = er.from_event_id
            JOIN events e2 ON e2.id = er.to_event_id
            WHERE er.from_event_id IN ({placeholders})
              AND er.to_event_id IN ({placeholders})
            ORDER BY er.id
        """, ids + ids).fetchall()

    return {'relations': [
        {'id': r[0], 'from_event_id': r[1], 'to_event_id': r[2], 'relation': r[3],
         'from_title': r[4], 'to_title': r[5], 'created_by': r[6]}
        for r in rows
    ]}

@router.post("/{relation_id}/confirm")
def confirm_relation(relation_id: int):
    db = get_db()
    ok = db.confirm_relation(relation_id)
    if not ok:
        raise HTTPException(404, "relation_not_found")
    return {'ok': True}

@router.delete("/{relation_id}")
def reject_relation(relation_id: int):
    db = get_db()
    ok = db.reject_relation(relation_id)
    if not ok:
        raise HTTPException(404, "relation_not_found")
    return {'ok': True}

class CreateRelation(BaseModel):
    from_event_id: int
    to_event_id: int
    relation: str  # before|after|update|spawn|related

@router.post("")
def create_relation(body: CreateRelation):
    db = get_db()
    if body.relation not in ('before', 'after', 'update', 'spawn', 'related'):
        raise HTTPException(400, "invalid_relation_type")
    ok = db.link_events(body.from_event_id, body.to_event_id, body.relation)
    if not ok:
        raise HTTPException(400, "failed_to_create_relation")
    return {'ok': True}
