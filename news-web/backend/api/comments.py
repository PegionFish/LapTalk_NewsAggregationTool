"""Comments API — 文章多级评语 + 点赞。

读取（GET）使用 optional_user，匿名也可查看；
写入（POST/PATCH/DELETE/like）必须登录，评语归属当前用户。
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional

from config import config
from db.news_db import NewsDB
from auth.auth import get_current_user, optional_user

# 不使用前缀，直接定义完整路径，便于同时承载
#   /api/articles/{id}/comments   与   /api/comments/{id}...
router = APIRouter(tags=["comments"])


def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)


def _ensure_article_exists(db: NewsDB, article_id: int) -> None:
    with db._conn() as conn:
        if not conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone():
            raise HTTPException(404, "article_not_found")


# ── 文章级评语 ──────────────────────────────────────────

@router.get("/api/articles/{article_id}/comments")
def list_comments(article_id: int, user: Optional[dict] = Depends(optional_user)):
    """获取文章评语列表（树形，含点赞数与 liked_by_me）。"""
    db = get_db()
    _ensure_article_exists(db, article_id)
    uid = int(user['id']) if user else 0
    return {'comments': db.get_comments(article_id, uid)}


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = None
    rating: Optional[int] = Field(None, ge=0, le=100)


@router.post("/api/articles/{article_id}/comments")
def add_comment(article_id: int, body: CommentCreate, user: dict = Depends(get_current_user)):
    """添加评语（或回复）。需要登录。"""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "content_empty")
    db = get_db()
    _ensure_article_exists(db, article_id)
    # 校验父评语存在且属于同一文章
    if body.parent_id is not None:
        with db._conn() as conn:
            row = conn.execute(
                "SELECT article_id FROM article_comments WHERE id=?", (body.parent_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "parent_comment_not_found")
        if row[0] != article_id:
            raise HTTPException(400, "parent_comment_mismatch")
    return db.add_comment(
        article_id, int(user['id']), user.get('display_name') or user.get('username') or 'anonymous',
        content, body.parent_id, body.rating
    )


# ── 单条评语操作 ────────────────────────────────────────

class CommentEdit(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    rating: Optional[int] = Field(None, ge=0, le=100)


@router.patch("/api/comments/{comment_id}")
def edit_comment(comment_id: int, body: CommentEdit, user: dict = Depends(get_current_user)):
    """编辑评语（仅作者本人）。"""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "content_empty")
    db = get_db()
    ok = db.edit_comment(comment_id, int(user['id']), content, body.rating)
    if not ok:
        raise HTTPException(403, "not_author_or_not_found")
    return {'ok': True}


@router.delete("/api/comments/{comment_id}")
def delete_comment(comment_id: int, user: dict = Depends(get_current_user)):
    """删除评语（仅作者本人），级联删除子评语与点赞。"""
    db = get_db()
    ok = db.delete_comment(comment_id, int(user['id']))
    if not ok:
        raise HTTPException(403, "not_author_or_not_found")
    return {'ok': True}


@router.post("/api/comments/{comment_id}/like")
def toggle_like(comment_id: int, user: dict = Depends(get_current_user)):
    """点赞 / 取消点赞（切换）。"""
    db = get_db()
    with db._conn() as conn:
        if not conn.execute("SELECT 1 FROM article_comments WHERE id=?", (comment_id,)).fetchone():
            raise HTTPException(404, "comment_not_found")
    return db.toggle_comment_like(comment_id, int(user['id']))
