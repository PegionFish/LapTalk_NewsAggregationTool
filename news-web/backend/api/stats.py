from fastapi import APIRouter, HTTPException
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/stats", tags=["stats"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def get_stats():
    db = get_db()
    return db.get_stats()
