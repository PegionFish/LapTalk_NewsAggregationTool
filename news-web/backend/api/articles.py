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
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags,
                   a.content_status, a.content_fetched_at,
                   a.content_lang, a.ai_analyzed, a.human_processed,
                   CASE WHEN a.translated_content != '' THEN 1 ELSE 0 END as has_translation
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
        'content_status': r[11] or 'pending',
        'content_fetched_at': r[12],
        'content_lang': r[13] or '',
        'ai_analyzed': bool(r[14]),
        'human_processed': bool(r[15]),
        'has_translation': bool(r[16]),
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
async def get_article_content(article_id: int):
    """获取文章内容 — 三级回退：DB缓存 → 磁盘文件 → 代理获取。
    返回结构化 JSON（原文 content + 译文 translation 独立不覆盖）。"""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT url, local_path, text_content, translated_content, content_lang, content_status, ai_summary, ai_analyzed, human_processed "
            "FROM articles WHERE id=?", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    url, local_path, text_content, translated_content, content_lang, content_status, ai_summary, ai_analyzed, human_processed = row

    # 1. DB 文本缓存已存在 → 直接返回
    if text_content:
        return {
            "url": url,
            "content": text_content,
            "translation": translated_content or "",
            "lang": content_lang,
            "status": content_status,
            "source": "local",
            "ai_summary": ai_summary or "",
            "ai_analyzed": bool(ai_analyzed),
            "human_processed": bool(human_processed),
        }

    # 2. 磁盘 HTML 文件存在 → 实时提取
    if local_path and not local_path.startswith('[ERR:'):
        import os
        cache_dir = config.content_cache_path
        full_path = os.path.join(cache_dir, os.path.basename(local_path))
        if os.path.isfile(full_path):
            from utils.text import extract_text_from_html, detect_language
            with open(full_path, 'r', encoding='utf-8') as f:
                html = f.read()
            text = extract_text_from_html(html)
            lang = detect_language(text)
            return {
                "url": url,
                "content": text,
                "translation": "",
                "lang": lang,
                "status": "cached",
                "source": "local",
            }

    # 3. 回退：代理获取原文
    if not url:
        raise HTTPException(404, "no_url")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers={'User-Agent': config.user_agent},
                                    follow_redirects=True, timeout=15)
            from utils.text import extract_text_from_html, detect_language
            html = resp.text
            text = extract_text_from_html(html)
            lang = detect_language(text)
            return {
                "url": url,
                "content": text,
                "translation": "",
                "lang": lang,
                "status": "proxied",
                "source": "remote",
            }
        except Exception as e:
            raise HTTPException(502, f"fetch_failed: {str(e)[:80]}")


def _inject_base(html: str, base_url: str) -> str:
    """在 <head> 中注入 <base href> 标签，使相对路径资源回源站加载。"""
    import re
    tag = f'<base href="{base_url}">'
    if re.search(r'<head[^>]*>', html, re.IGNORECASE):
        return re.sub(r'(<head[^>]*>)', rf'\1{tag}', html, count=1, flags=re.IGNORECASE)
    return tag + html


def _sanitize_html(html: str) -> str:
    """切除脚本和追踪标签，保留纯内容。"""
    import re
    # 1. 移除所有 <script>...</script>（含内联和外部）
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    # 2. 移除 <noscript>...</noscript>
    html = re.sub(r'<noscript[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
    # 3. 移除 inline event handlers (onload/onclick/onerror 等)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    # 4. 移除 <iframe> 标签（防止嵌套追踪）
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    # 5. 移除常见的追踪 pixel/beacon
    html = re.sub(r'<img[^>]+(?:pixel|tracking|beacon|analytics)[^>]*>', '', html, flags=re.IGNORECASE)
    # 6. 移除非样式表的 <link> 标签（manifest、icon、preconnect 等会触发 CORS 告警）
    # 负向先行断言用 [^>]* 限定在同一个 <link> 标签内检查
    _LINK_CORS = re.compile(
        r'<link\b(?![^>]*\brel\s*=\s*["\']stylesheet\b)[^>]*/?\s*>',
        re.IGNORECASE,
    )
    html = _LINK_CORS.sub('', html)
    return html


@router.get("/{article_id}/html")
async def serve_article_html(article_id: int):
    """返回文章 HTML — 优先本地缓存，已切除脚本/追踪标签。"""
    from fastapi.responses import HTMLResponse
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT url, local_path FROM articles WHERE id=?", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    url, local_path = row

    # 1. 本地 HTML 缓存 — 切除脚本后返回纯阅读内容
    if local_path and not local_path.startswith('[ERR:'):
        import os
        cache_dir = config.content_cache_path
        full_path = os.path.join(cache_dir, os.path.basename(local_path))
        if os.path.isfile(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                html = f.read()
            if url:
                html = _inject_base(html, url)
            html = _sanitize_html(html)
            return HTMLResponse(content=html, media_type="text/html")

    # 2. 回退代理获取 — 同样切除脚本
    if not url:
        raise HTTPException(404, "no_url")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers={'User-Agent': config.user_agent},
                                    follow_redirects=True, timeout=15)
            html = _sanitize_html(resp.text)
            return HTMLResponse(content=html, media_type="text/html")
        except Exception as e:
            raise HTTPException(502, f"fetch_failed: {str(e)[:80]}")


@router.post("/{article_id}/analyze")
def analyze_article(article_id: int):
    """对文章内容进行 AI 分析并缓存摘要。如已有分析直接返回。"""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT id, title, text_content, ai_summary, ai_analyzed FROM articles WHERE id=?",
            (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    aid, title, content, cached, analyzed = row

    if analyzed and cached:
        return {"ok": True, "cached": True, "analysis": cached,
                "ai_analyzed": True, "human_processed": bool(
                    conn.execute("SELECT human_processed FROM articles WHERE id=?", (aid,)).fetchone()[0]
                )}

    if not content:
        return {"ok": False, "error": "该文章尚未完成内容提取，暂无法分析", "no_content": True}

    from ai_client import analyze_article as ai_analyze
    try:
        analysis = ai_analyze(title, content)
    except Exception as e:
        raise HTTPException(502, f"ai_failed: {str(e)[:120]}")

    with db._conn() as conn:
        conn.execute(
            "UPDATE articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
            (analysis, article_id)
        )
        conn.commit()

    return {"ok": True, "cached": False, "analysis": analysis,
            "ai_analyzed": True}
