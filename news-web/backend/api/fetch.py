"""
数据采集状态监控 API — 抓取历史、源健康、缓存重试。
"""
import os, sqlite3, threading, logging, time
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from config import config

router = APIRouter(prefix="/api/fetch", tags=["fetch"])
logger = logging.getLogger(__name__)

# 源重试互斥 — 同一时间每个源只允许一个重试任务
_retry_locks: dict = {}
_retry_lock = threading.Lock()

# 最多缓存重试日志条数
LOG_MAX = 200
_retry_state: dict = {
    "running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []
}


def _conn():
    if not config.db_path:
        raise HTTPException(400, "database_not_configured")
    return sqlite3.connect(config.db_path)


def _get_new_db():
    from db.news_db import NewsDB
    return NewsDB(config.db_path)


# ══════════════════════════════════════════════════════════════
# 抓取总览
# ══════════════════════════════════════════════════════════════

@router.get("/overview")
def fetch_overview():
    """总览统计 — RSS/热榜/缓存 三维度概览。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    return db.get_fetch_overview()


# ══════════════════════════════════════════════════════════════
# 源列表
# ══════════════════════════════════════════════════════════════

@router.get("/sources")
def fetch_sources(source_type: str = Query("", description="筛选类型: rss | hotlist | bilibili")):
    """所有源的详情列表（含健康状态、成功率）。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    sources = db.get_fetch_sources(source_type=source_type or '')
    return {"sources": sources}


# ══════════════════════════════════════════════════════════════
# 单源历史
# ══════════════════════════════════════════════════════════════

@router.get("/sources/{name}/history")
def fetch_source_history(name: str, days: int = Query(7, ge=1, le=90)):
    """单源抓取历史记录。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    history = db.get_fetch_source_history(name, days=days)
    return {"source": name, "days": days, "history": history}


# ══════════════════════════════════════════════════════════════
# 源重试
# ══════════════════════════════════════════════════════════════

@router.post("/sources/{name}/retry")
def retry_fetch_source(name: str):
    """单源重抓 — 后台线程执行。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    with _retry_lock:
        if name in _retry_locks and _retry_locks[name]:
            return {"ok": False, "message": f"源 {name} 正在抓取中，请稍后再试"}

    # 确定源类型和 URL
    feed_info = None
    source_type = ''

    # 检查 RSS 源
    try:
        from pipeline.fetch_english_news import RSS_FEEDS
        for f in RSS_FEEDS:
            if f['name'] == name:
                feed_info = f
                source_type = 'rss'
                break
    except ImportError:
        pass

    if not feed_info:
        raise HTTPException(status_code=404, detail=f"未知源: {name}")

    with _retry_lock:
        _retry_locks[name] = True

    def _do_retry():
        started = datetime.now()
        try:
            from pipeline.fetch_english_news import fetch_feed
            from db.news_db import NewsDB
            db = NewsDB(config.db_path)
            items = fetch_feed(feed_info)
            fetched = len(items)
            saved, skipped = db.save_articles('rss_news', items)
            db.link_articles_to_events()
            elapsed = int((datetime.now() - started).total_seconds() * 1000)
            db.log_fetch(
                source_name=name, source_type=source_type,
                articles_fetched=fetched, articles_new=saved,
                status='ok', duration_ms=elapsed, run_type='manual'
            )
            logger.info(f"[fetch] 手动重抓 {name}: {saved} 新增/{fetched} 条, {elapsed}ms")
        except Exception as e:
            elapsed = int((datetime.now() - started).total_seconds() * 1000)
            try:
                db = NewsDB(config.db_path)
                db.log_fetch(
                    source_name=name, source_type=source_type,
                    articles_fetched=0, articles_new=0,
                    status='failed', error_msg=str(e)[:200],
                    duration_ms=elapsed, run_type='manual'
                )
            except Exception:
                pass
            logger.error(f"[fetch] 手动重抓 {name} 失败: {e}")
        finally:
            with _retry_lock:
                _retry_locks[name] = False

    threading.Thread(target=_do_retry, daemon=True).start()
    return {"ok": True, "message": f"开始重抓源: {name}"}


# ══════════════════════════════════════════════════════════════
# 源文章列表
# ══════════════════════════════════════════════════════════════

@router.get("/sources/{name}/articles")
def fetch_source_articles(
    name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("", description="缓存状态筛选: pending | fetched | failed | translated"),
):
    """该源文章列表 — 分页 + 按缓存状态筛选。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    where_clauses = ["source = ?"]
    params = [name]
    if status == 'pending':
        where_clauses.append("(local_path IS NULL OR local_path = '')")
    elif status == 'fetched':
        where_clauses.append("local_path != '' AND local_path NOT LIKE '[ERR:%'")
    elif status == 'failed':
        where_clauses.append("local_path LIKE '[ERR:%'")
    elif status == 'translated':
        where_clauses.append("translated_content != ''")

    where = " AND ".join(where_clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM articles WHERE {where}", params).fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute(f"""
        SELECT id, title, url, source, content_status, local_path,
               content_fetched_at, content_lang, translated_content
        FROM articles WHERE {where}
        ORDER BY id DESC LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()

    articles = []
    for r in rows:
        st = 'failed' if (r[5] or '').startswith('[ERR:') else (
            'translated' if r[8] else ('fetched' if r[5] else 'pending')
        )
        articles.append({
            'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
            'content_status': st,
            'local_path': r[5] or '',
            'content_fetched_at': r[6],
            'content_lang': r[7] or '',
            'has_translation': bool(r[8]),
        })

    return {"total": total, "page": page, "limit": limit, "source": name, "articles": articles}


# ══════════════════════════════════════════════════════════════
# 失败文章列表
# ══════════════════════════════════════════════════════════════

@router.get("/articles/failed")
def fetch_failed_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """下载失败的文章分页列表。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'"
    ).fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute("""
        SELECT id, title, url, source, local_path, content_fetched_at
        FROM articles WHERE local_path LIKE '[ERR:%'
        ORDER BY id DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()

    articles = [
        {
            'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
            'error': (r[4] or '[ERR:unknown]').replace('[ERR:', '').rstrip(']'),
            'content_fetched_at': r[5],
        }
        for r in rows
    ]
    return {"total": total, "page": page, "limit": limit, "articles": articles}


# ══════════════════════════════════════════════════════════════
# 单篇缓存重试
# ══════════════════════════════════════════════════════════════

@router.post("/articles/{article_id}/retry-cache")
def retry_article_cache(article_id: int):
    """单篇文章缓存重试 — 重新下载 HTML 并提取文本。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    row = conn.execute(
        "SELECT id, title, url FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "文章不存在")

    def _do_one():
        aid, title, url = row
        try:
            from pipeline.fetch_content import download_page, sanitize_html
            from utils.text import extract_text_from_html, detect_language
            from datetime import datetime as _dt

            if not url or not url.startswith('http'):
                _log_retry(f"#{aid} ⚠️ 无有效 URL，跳过")
                return

            _log_retry(f"#{aid} 📡 下载中...")
            res = download_page(url)
            if res['error']:
                conn2 = _conn()
                conn2.execute(
                    "UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                    (f"[ERR:{res['error']}]", _dt.now().isoformat(timespec='seconds'), aid)
                )
                conn2.commit(); conn2.close()
                _log_retry(f"#{aid} ❌ {res['error']}")
                return

            html = sanitize_html(res['html'])
            content_dir = config.content_cache_path
            os.makedirs(content_dir, exist_ok=True)
            file_path = os.path.join(content_dir, f'{aid}.html')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)

            text = extract_text_from_html(html)
            lang = detect_language(text)
            now = _dt.now().isoformat(timespec='seconds')
            rel_path = f'{os.path.basename(content_dir)}/{aid}.html'
            conn2 = _conn()
            conn2.execute("""
                UPDATE articles SET
                    local_path=?, content_fetched_at=?,
                    text_content=?, content_lang=?, content_status='fetched'
                WHERE id=?
            """, (rel_path, now, text, lang, aid))
            conn2.commit(); conn2.close()
            _log_retry(f"#{aid} ✅ 缓存成功 [{lang}] {len(html)//1024}KB")

            if lang == 'en' and config.translation_enabled and config.translation_api_key:
                try:
                    from translation_client import translate_to_chinese
                    translation = translate_to_chinese(text)
                    if translation:
                        conn2 = _conn()
                        conn2.execute("""
                            UPDATE articles SET
                                translated_content=?, content_status='translated', translated_at=?
                            WHERE id=?
                        """, (translation, _dt.now().isoformat(timespec='seconds'), aid))
                        conn2.commit(); conn2.close()
                        _log_retry(f"#{aid} ✅ 翻译完成")
                except Exception as e:
                    _log_retry(f"#{aid} ⚠️ 翻译失败: {str(e)[:300]}")
        except Exception as e:
            _log_retry(f"#{aid} ❌ {str(e)[:300]}")

    threading.Thread(target=_do_one, daemon=True).start()
    return {"ok": True, "message": f"开始重试文章 #{article_id} 的缓存下载"}


# ══════════════════════════════════════════════════════════════
# 批量缓存重试
# ══════════════════════════════════════════════════════════════

@router.post("/articles/batch-retry")
def retry_articles_batch(body: dict):
    """批量缓存重试 — 支持指定 ID 列表或重试所有失败文章。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    global _retry_state
    if _retry_state.get("running"):
        return {"ok": False, "message": "批量重试任务已在运行中"}

    retry_all = body.get('retry_all', False)
    ids = body.get('ids', [])

    if retry_all:
        # 获取所有失败文章
        conn = _conn()
        rows = conn.execute(
            "SELECT id FROM articles WHERE local_path LIKE '[ERR:%' "
            "AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
        ).fetchall()
        conn.close()
        ids = [r[0] for r in rows]
    elif not isinstance(ids, list) or not ids:
        raise HTTPException(400, "请提供文章 ID 列表或设置 retry_all=true")

    if len(ids) > 50:
        raise HTTPException(400, "单次批量重试最多支持 50 篇文章")

    if not ids:
        return {"ok": True, "total": 0, "message": "没有需要重试的文章"}

    _retry_state = {"running": True, "total": len(ids), "done": 0, "failed": 0, "current": "", "log": [], "source_delay": True}

    def _batch_retry():
        global _retry_state
        from pipeline.fetch_content import download_page, sanitize_html
        from utils.text import extract_text_from_html, detect_language
        from datetime import datetime as _dt
        import random

        # 按来源分组，同源文章之间延迟 5-10 秒
        conn = _conn()
        articles = []
        for aid in ids:
            row = conn.execute("SELECT id, title, url, source FROM articles WHERE id=?", (aid,)).fetchone()
            if row:
                articles.append(row)
        conn.close()

        # 按 source 分组
        by_source = {}
        for aid, title, url, source in articles:
            by_source.setdefault(source, []).append((aid, title, url))

        done_count = 0
        for source, items in by_source.items():
            for idx, (aid, title, url) in enumerate(items):
                _retry_state["current"] = f"#{aid} {title[:40]}"
                if not url or not url.startswith('http'):
                    _log_retry(f"#{aid} ⚠️ 无有效 URL")
                    _retry_state["failed"] += 1
                    _retry_state["done"] += 1
                    done_count += 1
                    continue

                try:
                    res = download_page(url)
                    if res['error']:
                        conn2 = _conn()
                        conn2.execute(
                            "UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                            (f"[ERR:{res['error']}]", _dt.now().isoformat(timespec='seconds'), aid)
                        )
                        conn2.commit(); conn2.close()
                        _log_retry(f"#{aid} ❌ {res['error']}")
                        _retry_state["failed"] += 1
                    else:
                        html = sanitize_html(res['html'])
                        content_dir = config.content_cache_path
                        os.makedirs(content_dir, exist_ok=True)
                        file_path = os.path.join(content_dir, f'{aid}.html')
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(html)

                        text = extract_text_from_html(html)
                        lang = detect_language(text)
                        now = _dt.now().isoformat(timespec='seconds')
                        rel_path = f'{os.path.basename(content_dir)}/{aid}.html'
                        conn2 = _conn()
                        conn2.execute("""
                            UPDATE articles SET
                                local_path=?, content_fetched_at=?,
                                text_content=?, content_lang=?, content_status='fetched'
                            WHERE id=?
                        """, (rel_path, now, text, lang, aid))
                        conn2.commit(); conn2.close()
                        _log_retry(f"#{aid} ✅ 缓存成功 [{lang}]")

                    _retry_state["done"] += 1
                    done_count += 1

                    # 同源文章之间延迟 5-10 秒，避免触发风控
                    if idx < len(items) - 1:
                        delay = random.uniform(5, 10)
                        _log_retry(f"⏳ 等待 {delay:.1f}s 后继续抓取 {source}...")
                        time.sleep(delay)
                    elif done_count < len(ids):
                        # 切换源时也短暂延迟
                        time.sleep(2)

                except Exception as e:
                    _log_retry(f"#{aid} ❌ {str(e)[:300]}")
                    _retry_state["failed"] += 1
                    _retry_state["done"] += 1
                    done_count += 1

        _retry_state["running"] = False
        _retry_state["current"] = "完成"

    threading.Thread(target=_batch_retry, daemon=True).start()
    return {"ok": True, "total": len(ids), "message": f"开始批量重试 {len(ids)} 篇缓存（同源间隔 5-10 秒）"}


@router.get("/articles/batch-retry/status")
def batch_retry_status():
    """查询批量重试进度。"""
    return dict(_retry_state)


# ══════════════════════════════════════════════════════════════
# 最近抓取日志
# ══════════════════════════════════════════════════════════════

@router.get("/logs")
def fetch_recent_logs(limit: int = Query(50, ge=1, le=200)):
    """全量最近抓取日志。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    logs = db.get_fetch_recent_logs(limit)
    return {"logs": logs}


# ── 内部工具 ──────────────────────────────────────────────

def _log_retry(msg: str):
    """批量重试进度记录。"""
    global _retry_state
    ts = datetime.now().strftime('%H:%M:%S')
    _retry_state["log"].append(f"[{ts}] {msg}")
    if len(_retry_state["log"]) > LOG_MAX:
        _retry_state["log"] = _retry_state["log"][-LOG_MAX:]
