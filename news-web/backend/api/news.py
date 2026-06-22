from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx, threading, time
from datetime import datetime
from config import config
from db.news_db import NewsDB
from utils.proxy import get_httpx_proxy

router = APIRouter(prefix="/api/news", tags=["news"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_news_articles(
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
    """Search news_articles with multi-dimensional filtering + 排序。

    sort: fetched_desc(默认) | score_desc | score_asc | date_desc
    """
    db = get_db()
    with db._conn() as conn:
        # 默认排除热榜/视频趋势数据（有独立展示页面）
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

        count = conn.execute(f"SELECT COUNT(*) FROM news_articles a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags,
                   a.content_status, a.content_fetched_at,
                   a.content_lang, a.ai_analyzed, a.human_processed, a.topic_category,
                   CASE WHEN a.translated_content != '' THEN 1 ELSE 0 END as has_translation,
                   a.local_path, a.retry_count
            FROM news_articles a WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

    import json
    news_articles = [{
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
        'local_path': r[18] or '',
        'retry_count': r[19] or 0,
    } for r in rows]

    return {'articles': news_articles, 'total': count, 'page': page, 'limit': limit}


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
def cleanup_preview(threshold: float = Query(20, ge=0, le=100)):
    """预览将被清理的文章数（不执行删除）。百分制阈值，默认 20。"""
    db = get_db()
    return db.preview_cleanup(threshold)


class CleanupRequest(BaseModel):
    threshold: float = 20


@router.post("/cleanup")
def cleanup_execute(body: CleanupRequest):
    """执行低分新闻清理。删除评分低于阈值且未被人工处理的文章及其关联数据。"""
    if body.threshold < 0 or body.threshold > 100:
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
            FROM news_articles a WHERE a.id=?
        """, (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "article_not_found")
        # Find event membership
        evt = conn.execute("""
            SELECT e.id, e.title FROM events e
            JOIN news_article_events ae ON ae.event_id = e.id
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
            conn.execute("UPDATE news_articles SET human_verified=? WHERE id=?", (body.human_verified, article_id))
            conn.commit()
    return {'ok': True}

@router.get("/{article_id}/content")
async def get_article_content(article_id: int):
    """获取文章内容 — 四级回退：DB缓存 → 磁盘文件 → 按需下载 → 返回链接。
    未缓存文章首次打开时自动下载并存盘。死链文章直接返回死链状态，不重试下载。"""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT url, local_path, text_content, translated_content, content_lang, content_status, ai_summary, ai_analyzed, human_processed "
            "FROM news_articles WHERE id=?", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    url, local_path, text_content, translated_content, content_lang, content_status, ai_summary, ai_analyzed, human_processed = row

    # 死链文章不尝试重新下载 — 直接返回死链状态
    if content_status == 'dead':
        return {
            "url": url,
            "content": "",
            "translation": "",
            "lang": content_lang or "",
            "status": "dead_link",
            "source": "link_only",
            "summary": ai_summary or "",
            "ai_analyzed": bool(ai_analyzed),
            "human_processed": bool(human_processed),
            "has_pdf": False,
            "downloaded": False,
        }

    def _has_pdf() -> bool:
        try:
            import os
            return os.path.isfile(os.path.join(config.content_cache_path, f'{article_id}.pdf'))
        except Exception:
            return False

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
            "has_pdf": _has_pdf(),
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
                conn2.execute("UPDATE news_articles SET text_content=?, content_lang=?, content_status='fetched' WHERE id=?",
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
                "has_pdf": _has_pdf(),
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
                    UPDATE news_articles SET local_path=?, content_fetched_at=?,
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
                    "has_pdf": _has_pdf(),
                }
        except Exception:
            pass

        # 3b. HTTP 失败 → Playwright 浏览器兜底（带真实指纹 + 挑战检测）
        try:
            from pipeline.browser_capture import fetch_with_fallback, cache_article_html
            pw_result = fetch_with_fallback(url, article_id)
            challenge = pw_result.get('challenge', {})

            if pw_result.get('html') and not challenge.get('is_challenge'):
                cache_article_html(article_id, pw_result['html'])
                content_dir = config.content_cache_path
                file_path = os.path.join(content_dir, f'{article_id}.html')
                if os.path.isfile(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        html = f.read()
                    text = extract_text_from_html(html)
                    lang = detect_language(text)
                    return {
                        "url": url,
                        "content": text,
                        "translation": "",
                        "lang": lang,
                        "status": "fetched",
                        "source": pw_result.get('source', 'playwright'),
                        "has_pdf": _has_pdf(),
                    }
            elif challenge.get('is_challenge'):
                return {
                    "url": url or "",
                    "content": "",
                    "translation": "",
                    "lang": "",
                    "status": "challenge",
                    "source": "challenge",
                    "challenge_type": challenge.get('type', 'unknown'),
                    "challenge_reason": challenge.get('reason', '需要人机验证'),
                    "has_pdf": _has_pdf(),
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
        "has_pdf": _has_pdf(),
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
    # 7. 移除 JS 框架指令属性（Alpine.js x-*, Vue v-*, Angular ng-* 等）
    # 这些属性在无脚本环境下无意义，且可能触发浏览器的 XSS 审计
    html = re.sub(r'\s+x-(?:data|html|init|show|cloak|bind|on|model|effect|ref|text|if|for|teleport|transition|ignore|id)\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+x-(?:data|html|init|show|cloak|bind|on|model|effect|ref|text|if|for|teleport|transition|ignore|id)\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+v-(?:if|else|for|bind|on|model|html|text|show|cloak|once|pre)\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+v-(?:if|else|for|bind|on|model|html|text|show|cloak|once|pre)\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+ng-(?:app|controller|bind|model|click|change|submit|init|cloak|show|hide|if|for|switch|class|style)\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+ng-(?:app|controller|bind|model|click|change|submit|init|cloak|show|hide|if|for|switch|class|style)\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    # 7b. 移除无值的框架布尔属性（如 <div x-cloak>）
    html = re.sub(r'\s+x-cloak\b', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+v-cloak\b', '', html, flags=re.IGNORECASE)
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
            "SELECT url, local_path FROM news_articles WHERE id=?", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    url, local_path = row

    # 通用安全头：明确禁止脚本执行，消除浏览器扩展注入告警
    _secure_headers = {"Content-Security-Policy": "script-src 'none'; object-src 'none'"}

    def _mk_response(content: str, extra_headers: dict | None = None) -> HTMLResponse:
        """构建带安全头的 HTML 响应，消除 sandbox 脚本拦截警告。"""
        headers = dict(_secure_headers)
        if extra_headers:
            headers.update(extra_headers)
        return HTMLResponse(content=content, media_type="text/html", headers=headers)

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
            return _mk_response(html)

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
                    UPDATE news_articles SET local_path=?, content_fetched_at=?,
                        text_content=?, content_lang=?, content_status='fetched'
                    WHERE id=?
                """, (rel_path, now, text, lang, article_id))
                conn2.commit()
                conn2.close()

                if url:
                    html = _inject_base(html, url)
                html = _sanitize_html(html)
                return _mk_response(html)
        except Exception:
            pass

    # 3. HTTP 下载失败 → Playwright 浏览器渲染兜底（带真实指纹）
    if url and url.startswith('http'):
        try:
            from pipeline.browser_capture import fetch_with_fallback, cache_article_html
            pw_result = fetch_with_fallback(url, article_id)
            challenge = pw_result.get('challenge', {})

            if pw_result.get('html') and not challenge.get('is_challenge'):
                # 成功获取 → 缓存并返回
                cache_article_html(article_id, pw_result['html'])
                cache_dir = config.content_cache_path
                file_path = os.path.join(cache_dir, f'{article_id}.html')
                if os.path.isfile(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        html = f.read()
                    if url:
                        html = _inject_base(html, url)
                    html = _sanitize_html(html)
                    return _mk_response(html, {"X-Capture-Source": pw_result.get('source', 'playwright')})
            elif challenge.get('is_challenge'):
                # 检测到人机验证 → 返回带验证提示的 fallback 页
                chal_type = challenge.get('type', 'unknown')
                chal_reason = challenge.get('reason', '需要人机验证')
                chal_fallback = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="x-challenge" content="{chal_type}"><style>
                    body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center; justify-content: center;
                           height: 100vh; margin: 0; background: #f5f5f5; color: #333; flex-direction: column; gap: 12px; text-align: center; padding: 24px; }}
                    .icon {{ font-size: 48px; color: #e68a00; }}
                    h3 {{ margin: 0; font-size: 16px; font-weight: 600; }}
                    p {{ margin: 0; font-size: 13px; color: #666; line-height: 1.5; }}
                    .btn {{ display: inline-block; padding: 10px 24px; background: #00d4ff; color: #fff; border-radius: 8px;
                           text-decoration: none; font-size: 14px; font-weight: 500; margin-top: 8px; }}
                    .btn:hover {{ background: #00b8e6; }}
                    .hint {{ color: #999; font-size: 11px; }}
                </style></head><body>
                    <div class="icon"><i class="fas fa-shield-halved"></i></div>
                    <h3>需要人机验证</h3>
                    <p>{chal_reason}<br>请用你的浏览器打开原站完成验证</p>
                    <a class="btn" href="{url}" target="_blank" rel="noopener">
                        打开原站验证 <i class="fas fa-external-link-alt"></i>
                    </a>
                    <p class="hint">验证通过后，返回此页面使用"手动粘贴内容"功能即可加载</p>
                </body></html>"""
                return _mk_response(chal_fallback, {"X-Challenge-Type": chal_type})
        except Exception:
            pass

    # 4. 全部无法获取 → 返回提示页面（前端会检测并展示 fallback UI）
    fallback = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center; justify-content: center;
               height: 100vh; margin: 0; background: #f5f5f5; color: #666; flex-direction: column; gap: 16px; }}
        a {{ color: var(--accent, #00d4ff); text-decoration: none; padding: 8px 16px; border: 1px solid currentColor;
             border-radius: 6px; font-size: 13px; }}
        a:hover {{ background: rgba(0,212,255,0.1); }}
    </style></head><body>
        <p style="font-size:13px;color:#999">服务器无法直接获取此页面内容</p>
        <a href="{url}" target="_blank" rel="noopener">在浏览器中打开原文 <i class="fas fa-external-link-alt"></i></a>
    </body></html>"""
    return _mk_response(fallback)


@router.post("/{article_id}/analyze")
def analyze_article(article_id: int):
    """对文章内容进行 AI 分析并缓存摘要。如已有分析直接返回。"""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT id, title, text_content, ai_summary, ai_analyzed FROM news_articles WHERE id=?",
            (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    aid, title, content, cached, analyzed = row

    if analyzed and cached:
        return {"ok": True, "cached": True, "analysis": cached,
                "ai_analyzed": True, "human_processed": bool(
                    conn.execute("SELECT human_processed FROM news_articles WHERE id=?", (aid,)).fetchone()[0]
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
            "UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
            (analysis, article_id)
        )
        conn.commit()

    return {"ok": True, "cached": False, "analysis": analysis,
            "ai_analyzed": True}


@router.get("/{article_id}/cleaned-content")
def get_cleaned_content(article_id: int):
    """获取 AI 清洗后的文章正文 HTML。缓存优先，首次调用触发 AI 清洗。"""
    import os, sqlite3 as _sqlite3

    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT id, url, local_path, ai_cleaned_content FROM news_articles WHERE id=?",
            (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "article_not_found")

    aid, url, local_path, cached_cleaned = row

    # 1. 有缓存直接返回
    if cached_cleaned:
        return {"cleaned": cached_cleaned, "cached": True, "source": "cache"}

    # 2. 需要读取 HTML 并调用 AI 清洗
    if not local_path or local_path.startswith('[ERR:'):
        return {"cleaned": "", "cached": False, "error": "no_html_available"}

    cache_dir = config.content_cache_path
    full_path = os.path.join(cache_dir, os.path.basename(local_path))
    if not os.path.isfile(full_path):
        return {"cleaned": "", "cached": False, "error": "html_file_not_found"}

    with open(full_path, 'r', encoding='utf-8') as f:
        html = f.read()

    html = _sanitize_html(html)
    if len(html) < 100:
        return {"cleaned": "", "cached": False, "error": "html_too_short"}

    from ai_client import clean_article_content
    try:
        cleaned = clean_article_content(html)
        if not cleaned:
            return {"cleaned": "", "cached": False, "error": "ai_returned_empty"}
        # 安全防线：对 AI 输出再做一次 sanitize
        cleaned = _sanitize_html(cleaned)

        # 缓存结果到 DB
        conn2 = _sqlite3.connect(config.db_path)
        conn2.execute(
            "UPDATE news_articles SET ai_cleaned_content=? WHERE id=?",
            (cleaned, article_id)
        )
        conn2.commit()
        conn2.close()

        return {"cleaned": cleaned, "cached": False, "source": "ai"}
    except Exception as e:
        raise HTTPException(502, f"ai_cleaning_failed: {str(e)[:200]}")


class CacheHtmlRequest(BaseModel):
    html: str


@router.post("/{article_id}/cache-html")
def cache_article_html_endpoint(article_id: int, body: CacheHtmlRequest):
    """接收前端/浏览器工具提交的 HTML 内容并缓存到本地。"""
    from pipeline.browser_capture import cache_article_html

    if not body.html or len(body.html) < 50:
        raise HTTPException(400, "html_content_too_short")

    try:
        result = cache_article_html(article_id, body.html)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(500, f"cache_failed: {str(e)[:200]}")


class CachePdfRequest(BaseModel):
    pdf_base64: str


@router.post("/{article_id}/cache-pdf")
def cache_article_pdf(article_id: int, body: CachePdfRequest):
    """接收前端提交的 PDF（base64）并保存到缓存目录。"""
    import base64, os
    try:
        pdf_data = base64.b64decode(body.pdf_base64)
        content_dir = config.content_cache_path
        os.makedirs(content_dir, exist_ok=True)
        pdf_path = os.path.join(content_dir, f'{article_id}.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_data)
        return {"ok": True, "pdf_path": pdf_path}
    except Exception as e:
        raise HTTPException(500, f"pdf_cache_failed: {str(e)[:200]}")


@router.get("/{article_id}/pdf")
async def serve_article_pdf(article_id: int):
    """返回文章 PDF 缓存文件。"""
    import os
    from fastapi.responses import FileResponse
    pdf_path = os.path.join(config.content_cache_path, f'{article_id}.pdf')
    if not os.path.isfile(pdf_path):
        raise HTTPException(404, "pdf_not_found")
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f'article_{article_id}.pdf')


# ══════════════════════════════════════════════════════════════
# 死链验证 — 复查所有 404/410 文章
# ══════════════════════════════════════════════════════════════

@router.post("/verify-dead")
def verify_dead_links():
    """复查所有疑似死链 (404/410/451)，返回可一键重试的列表。

    不自动标记 dead — 由用户在 UI 中手动确认。
    """
    import sqlite3
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("""
        SELECT id, title, url, source, local_path, retry_count, content_status
        FROM news_articles
        WHERE local_path LIKE '[ERR:HTTP 404%'
           OR local_path LIKE '[ERR:HTTP 410%'
           OR local_path LIKE '[ERR:HTTP 451%'
        ORDER BY retry_count DESC, id
    """).fetchall()
    conn.close()

    suspects = []
    confirmed_dead = 0
    for r in rows:
        error = (r[4] or '[ERR:unknown]').replace('[ERR:', '').rstrip(']')
        is_dead = r[6] == 'dead'
        if is_dead:
            confirmed_dead += 1
        suspects.append({
            'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
            'error': error, 'retry_count': r[5] or 0,
            'is_dead': is_dead,
        })

    return {
        'total': len(suspects),
        'confirmed_dead': confirmed_dead,
        'suspects': suspects,
        'note': 'retry_count≥2 的文章已被自动标记 dead。'
                '如需解标记，调用 PATCH /api/news/{id} 设置 content_status 为空。',
    }


# ══════════════════════════════════════════════════════════════
# 死链 URL 恢复 — 搜索引擎查找新链接
# ══════════════════════════════════════════════════════════════

_recover_state: dict = {
    "running": False, "total": 0, "done": 0, "recovered": 0,
    "not_found": 0, "current": "", "log": [], "started_at": "",
}


@router.post("/recover-dead")
def recover_dead_links(body: dict):
    """通过搜索引擎查找死链文章的新 URL。支持指定 ID 或全部。

    body: { ids: number[] } 或 { retry_all: true }
    """
    global _recover_state
    if _recover_state.get("running"):
        return {"ok": False, "message": "恢复任务已在运行中"}

    if not config.db_path:
        return {"error": "database_not_configured"}

    retry_all = body.get('retry_all', False)
    ids = body.get('ids', [])

    if retry_all:
        import sqlite3
        conn = sqlite3.connect(config.db_path)
        rows = conn.execute("""
            SELECT id FROM news_articles
            WHERE (local_path LIKE '[ERR:HTTP 404%' OR local_path LIKE '[ERR:HTTP 410%')
            AND content_status != 'dead'
        """).fetchall()
        conn.close()
        ids = [r[0] for r in rows]
    elif not ids:
        from fastapi import HTTPException
        raise HTTPException(400, "请提供文章 ID 列表或设置 retry_all=true")

    if not ids:
        return {"ok": True, "total": 0, "message": "没有需要恢复的文章"}

    _recover_state.update({
        "running": True, "total": len(ids), "done": 0, "recovered": 0,
        "not_found": 0, "current": "", "log": [],
        "started_at": datetime.now().isoformat(),
    })

    def _do_recover():
        global _recover_state
        import sqlite3, random
        from pipeline.dead_link_recovery import recover_article

        for aid in ids:
            conn2 = sqlite3.connect(config.db_path)
            row = conn2.execute(
                "SELECT title FROM news_articles WHERE id=?", (aid,)
            ).fetchone()
            conn2.close()
            title = row[0][:60] if row else str(aid)

            _recover_state["current"] = f"#{aid} {title}"
            ts = datetime.now().strftime('%H:%M:%S')
            _recover_state["log"].append(f"[{ts}] 🔍 搜索: #{aid} {title}")

            r = recover_article(aid)
            _recover_state["done"] += 1

            if r['status'] == 'recovered':
                _recover_state["recovered"] += 1
                _recover_state["log"].append(f"[{ts}] ✅ #{aid} → {r.get('new_url', '?')[:80]}")
            else:
                _recover_state["not_found"] += 1
                _recover_state["log"].append(f"[{ts}] ❌ #{aid} {r.get('message', '')[:60]}")

            # 速率限制
            time.sleep(random.uniform(4, 8))

        _recover_state["running"] = False
        _recover_state["current"] = "完成"

    threading.Thread(target=_do_recover, daemon=True).start()
    return {
        "ok": True, "total": len(ids),
        "message": f"开始搜索恢复 {len(ids)} 篇死链（DDG 搜索，间隔 4-8 秒）"
    }


@router.get("/recover-dead/status")
def recover_dead_status():
    """查询死链恢复任务进度。"""
    s = dict(_recover_state)
    if s.get("started_at"):
        try:
            started = datetime.fromisoformat(s["started_at"])
            s["elapsed_seconds"] = int((datetime.now() - started).total_seconds())
        except (ValueError, TypeError):
            s["elapsed_seconds"] = 0
    return s
