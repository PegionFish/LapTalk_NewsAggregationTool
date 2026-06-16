from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx
from config import config
from db.news_db import NewsDB
from utils.proxy import get_httpx_proxy

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
    topic_category: str = "",
    sort: str = "fetched_desc",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """Search articles with multi-dimensional filtering + 排序。

    sort: fetched_desc(默认) | score_desc | score_asc | date_desc
    """
    db = get_db()
    with db._conn() as conn:
        # 默认排除热榜/视频趋势数据（有独立展示页面）
        clauses = ["a.category NOT IN ('platform_hotlists', 'bilibili_videos')"]
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
        if topic_category:
            clauses.append("a.topic_category = ?")
            params.append(topic_category)

        where = " AND ".join(clauses) if clauses else "1=1"
        offset = (page - 1) * limit

        # 排序：score_* 优先按 priority_score；date_desc 按发布日期；其余按 fetched_at
        order_map = {
            'score_desc': "a.priority_score DESC, a.fetched_at DESC",
            'score_asc': "a.priority_score ASC, a.fetched_at DESC",
            'date_desc': "a.published_date DESC, a.fetched_at DESC",
            'fetched_desc': "a.fetched_at DESC",
        }
        order_by = order_map.get(sort, order_map['fetched_desc'])

        count = conn.execute(f"SELECT COUNT(*) FROM articles a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags,
                   a.content_status, a.content_fetched_at,
                   a.content_lang, a.ai_analyzed, a.human_processed, a.topic_category,
                   CASE WHEN a.translated_content != '' THEN 1 ELSE 0 END as has_translation
            FROM articles a WHERE {where}
            ORDER BY {order_by}
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
        'topic_category': r[16] or '',
        'has_translation': bool(r[17]),
    } for r in rows]

    return {'articles': articles, 'total': count, 'page': page, 'limit': limit}


@router.get("/categories")
def list_categories():
    """返回各主题分类的文章数统计（供前端 Tab badge）。"""
    db = get_db()
    return {'categories': db.get_topic_stats()}


@router.post("/categories/populate")
def populate_categories():
    """为所有已有文章填充 topic_category（批量回填）。"""
    db = get_db()
    updated = db.populate_topic_categories()
    return {'ok': True, 'updated': updated, 'categories': db.get_topic_stats()}


# ── 低分新闻清理 ────────────────────────────────────────

@router.get("/cleanup/preview")
def cleanup_preview(threshold: float = Query(0.2, ge=0.0, le=1.0)):
    """预览将被清理的文章数（不执行删除）。"""
    db = get_db()
    return db.preview_cleanup(threshold)


class CleanupRequest(BaseModel):
    threshold: float = 0.2


@router.post("/cleanup")
def cleanup_execute(body: CleanupRequest):
    """执行低分新闻清理。删除评分低于阈值且未被人工处理的文章及其关联数据。"""
    if body.threshold < 0.0 or body.threshold > 1.0:
        raise HTTPException(400, "threshold_out_of_range")
    db = get_db()
    preview = db.preview_cleanup(body.threshold)
    result = db.cleanup_low_score(body.threshold)
    return {'deleted': result['deleted'], 'threshold': body.threshold, 'would_delete': preview['count']}


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
    """获取文章内容 — 四级回退：DB缓存 → 磁盘文件 → 按需下载 → 返回链接。
    未缓存文章首次打开时自动下载并存盘。"""
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
            # 回填 DB
            try:
                conn2 = sqlite3.connect(config.db_path)
                conn2.execute("UPDATE articles SET text_content=?, content_lang=?, content_status='fetched' WHERE id=?",
                              (text, lang, article_id))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
            return {
                "url": url,
                "content": text,
                "translation": "",
                "lang": lang,
                "status": "cached",
                "source": "local",
            }

    # 3. 未缓存 → 按需下载并存盘
    if url and url.startswith('http'):
        try:
            from pipeline.fetch_content import download_page, sanitize_html
            from utils.text import extract_text_from_html, detect_language
            import os, sqlite3 as _sqlite3
            from datetime import datetime

            result = download_page(url, retries=1)
            if result.get('html') and not result.get('error'):
                html = sanitize_html(result['html'])
                content_dir = config.content_cache_path
                os.makedirs(content_dir, exist_ok=True)
                file_path = os.path.join(content_dir, f'{article_id}.html')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)

                text = extract_text_from_html(html)
                lang = detect_language(text)
                now = datetime.now().isoformat(timespec='seconds')
                rel_path = f'{os.path.basename(content_dir)}/{article_id}.html'

                conn2 = _sqlite3.connect(config.db_path)
                conn2.execute("""
                    UPDATE articles SET local_path=?, content_fetched_at=?,
                        text_content=?, content_lang=?, content_status='fetched'
                    WHERE id=?
                """, (rel_path, now, text, lang, article_id))
                conn2.commit()
                conn2.close()

                return {
                    "url": url,
                    "content": text,
                    "translation": "",
                    "lang": lang,
                    "status": "fetched",
                    "source": "on_demand",
                }
        except Exception:
            pass

    # 4. 全部失败 → 返回 URL 让用户自己打开
    return {
        "url": url or "",
        "content": "",
        "translation": "",
        "lang": "",
        "status": "no_cache",
        "source": "link_only",
    }


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
    """返回文章 HTML — 本地缓存优先，未缓存时按需下载并存盘。"""
    from fastapi.responses import HTMLResponse
    import os, sqlite3 as _sqlite3
    from datetime import datetime

    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT url, local_path FROM articles WHERE id=?", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    url, local_path = row

    # 1. 本地 HTML 缓存
    if local_path and not local_path.startswith('[ERR:'):
        cache_dir = config.content_cache_path
        full_path = os.path.join(cache_dir, os.path.basename(local_path))
        if os.path.isfile(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                html = f.read()
            if url:
                html = _inject_base(html, url)
            html = _sanitize_html(html)
            return HTMLResponse(content=html, media_type="text/html")

    # 2. 未缓存 → 按需下载并存盘
    if url and url.startswith('http'):
        try:
            from pipeline.fetch_content import download_page
            result = download_page(url, retries=1)
            if result.get('html') and not result.get('error'):
                from utils.text import extract_text_from_html, detect_language
                html = result['html']
                cache_dir = config.content_cache_path
                os.makedirs(cache_dir, exist_ok=True)
                file_path = os.path.join(cache_dir, f'{article_id}.html')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)

                text = extract_text_from_html(html)
                lang = detect_language(text)
                now = datetime.now().isoformat(timespec='seconds')
                rel_path = f'{os.path.basename(cache_dir)}/{article_id}.html'

                conn2 = _sqlite3.connect(config.db_path)
                conn2.execute("""
                    UPDATE articles SET local_path=?, content_fetched_at=?,
                        text_content=?, content_lang=?, content_status='fetched'
                    WHERE id=?
                """, (rel_path, now, text, lang, article_id))
                conn2.commit()
                conn2.close()

                if url:
                    html = _inject_base(html, url)
                html = _sanitize_html(html)
                return HTMLResponse(content=html, media_type="text/html")
        except Exception:
            pass

    # 3. 无法获取 → 返回简洁提示页
    fallback = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center; justify-content: center;
               height: 100vh; margin: 0; background: #f5f5f5; color: #666; flex-direction: column; gap: 16px; }}
        a {{ color: var(--accent, #00d4ff); text-decoration: none; padding: 8px 16px; border: 1px solid currentColor;
             border-radius: 6px; font-size: 13px; }}
        a:hover {{ background: rgba(0,212,255,0.1); }}
    </style></head><body>
        <i class="fas fa-link" style="font-size:32px; color:#ccc;"></i>
        <p>内容暂未缓存</p>
        <a href="{url}" target="_blank" rel="noopener">在原站阅读 <i class="fas fa-external-link-alt"></i></a>
    </body></html>"""
    return HTMLResponse(content=fallback, media_type="text/html")


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
