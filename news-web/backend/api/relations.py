from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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
