"""Audit log API — activity feed for the dashboard."""
from fastapi import APIRouter, HTTPException, Query, Depends
from config import config
from db.audit import get_audit_log as db_get_audit_log
from auth.auth import optional_user

router = APIRouter(prefix="/api/audit", tags=["audit"])

@router.get("")
def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    entity_type: str = Query('', description="article|event|chain|relation"),
):
    """Recent activity across all entities."""
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    return {
        'entries': db_get_audit_log(config.db_path, limit=limit, entity_type=entity_type),
        'total': len(db_get_audit_log(config.db_path, limit=1000, entity_type=entity_type)),
    }
