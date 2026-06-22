"""
数据采集状态监控 API — 抓取历史、源健康、缓存重试、调度管理。
"""
import os, sqlite3, threading, logging, time, random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config import config
from scheduler import get_schedule_info, get_schedule_logs, reload_scheduler

router = APIRouter(prefix="/api/fetch", tags=["fetch"])
logger = logging.getLogger(__name__)

# 源重试互斥 — 同一时间每个源只允许一个重试任务
_retry_locks: dict = {}
_retry_lock = threading.Lock()

_retry_state: dict = {
    "running": False, "total": 0, "done": 0, "failed": 0, "skipped": 0,
    "current": "", "log": [], "started_at": "", "cancelled": False
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

_WORKERS = 4          # 并行 worker 数 — 多源场景下大幅提速
_RETRY_TIMEOUT = 60   # 已知失败文章的超时秒数
DEAD_CODES = {404, 410, 451}  # 永久死链 — 不重试
# 403 / 网络错误会走 Playwright fallback

@router.post("/articles/batch-retry")
def retry_articles_batch(body: dict):
    """批量缓存重试 — 支持指定 ID 列表或重试所有失败文章。

    多源并行（4 线程），同源串行（锁 + 5-10s 间隔），404 死链自动跳过，
    403/网络错误自动 Playwright 渲染回退。
    """
    if not config.db_path:
        return {"error": "database_not_configured"}

    global _retry_state
    if _retry_state.get("running"):
        return {"ok": False, "message": "批量重试任务已在运行中"}

    retry_all = body.get('retry_all', False)
    ids = body.get('ids', [])

    if retry_all:
        conn = _conn()
        rows = conn.execute(
            "SELECT id FROM articles WHERE local_path LIKE '[ERR:%' "
            "AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
        ).fetchall()
        conn.close()
        ids = [r[0] for r in rows]
    elif not isinstance(ids, list) or not ids:
        raise HTTPException(400, "请提供文章 ID 列表或设置 retry_all=true")

    if len(ids) > 500:
        raise HTTPException(400, "单次批量重试最多支持 500 篇文章")

    if not ids:
        return {"ok": True, "total": 0, "message": "没有需要重试的文章"}

    _retry_state = {
        "running": True, "total": 0, "done": 0, "failed": 0, "skipped": 0,
        "current": "", "log": [], "started_at": datetime.now().isoformat(),
        "cancelled": False
    }

    def _batch_retry():
        global _retry_state
        from pipeline.fetch_content import download_page, sanitize_html
        from pipeline.browser_capture import fetch_with_fallback
        from utils.text import extract_text_from_html, detect_language
        from datetime import datetime as _dt

        # ── 查询所有文章，按源分组 ──
        conn = _conn()
        articles = []
        for aid in ids:
            row = conn.execute(
                "SELECT id, title, url, source FROM articles WHERE id=?", (aid,)
            ).fetchone()
            if row:
                articles.append(row)
        conn.close()

        # ── 预筛：分离死链 ──
        to_retry = []
        skipped = 0
        for aid, title, url, source in articles:
            if not url or not url.startswith('http'):
                _log_retry(f"#{aid} ⚠️ 无有效 URL — 跳过")
                skipped += 1
                continue
            # 检查原错误是否为死链
            conn2 = _conn()
            err_row = conn2.execute(
                "SELECT local_path FROM articles WHERE id=?", (aid,)
            ).fetchone()
            conn2.close()
            if err_row and err_row[0]:
                err_msg = str(err_row[0]).replace('[ERR:', '').rstrip(']')
                for code in DEAD_CODES:
                    if f'HTTP {code}' in err_msg:
                        _log_retry(f"#{aid} 💀 HTTP {code} 死链 — 跳过")
                        skipped += 1
                        break
                else:
                    to_retry.append((aid, title, url, source))
            else:
                to_retry.append((aid, title, url, source))

        _retry_state["total"] = len(to_retry)
        _retry_state["skipped"] = skipped
        _retry_state["done"] = 0

        if not to_retry:
            _retry_state["running"] = False
            _retry_state["current"] = "完成（全部跳过）"
            return

        # ── 按 source 创建锁 — 同源串行，不同源并行 ──
        source_locks: dict[str, threading.Lock] = {}
        lock_registry = threading.Lock()

        def get_source_lock(source: str) -> threading.Lock:
            with lock_registry:
                if source not in source_locks:
                    source_locks[source] = threading.Lock()
                return source_locks[source]

        # ── 单篇文章重试 worker ──
        def _do_retry_one(article: tuple) -> dict:
            aid, title, url, source = article

            # 检查取消
            if _retry_state.get("cancelled"):
                return {"status": "cancelled", "aid": aid}

            s_lock = get_source_lock(source)
            with s_lock:
                if _retry_state.get("cancelled"):
                    return {"status": "cancelled", "aid": aid}

                _retry_state["current"] = f"#{aid} [{source}] {title[:50]}"
                _log_retry(f"#{aid} 📡 [{source}] {title[:60]}")

                try:
                    res = download_page(url, retries=1, timeout=_RETRY_TIMEOUT)

                    # Playwright fallback for retryable HTTP errors
                    if res.get('error'):
                        err = res['error']
                        fallback_triggers = ('403', 'timed out', 'Connection refused',
                                             'Connection reset', 'Service Unavailable')
                        if any(k in err for k in fallback_triggers):
                            _log_retry(f"#{aid} 🎭 HTTP 失败，尝试 Playwright 渲染...")
                            try:
                                fb = fetch_with_fallback(url, aid)
                                if fb.get('html') and fb.get('source') not in ('challenge', 'failed') and len(fb.get('html', '')) > 200:
                                    res = {'html': fb['html'], 'error': None}
                                    _log_retry(f"#{aid} ✅ Playwright 渲染成功 [{fb.get('source', '?')}] {len(fb['html'])//1024}KB")
                                else:
                                    _log_retry(f"#{aid} ⚠️ Playwright 也未成功: {fb.get('source', '?')}")
                            except Exception as pe:
                                _log_retry(f"#{aid} ⚠️ Playwright 异常: {str(pe)[:200]}")

                    if res.get('error'):
                        conn2 = _conn()
                        conn2.execute(
                            "UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                            (f"[ERR:{res['error']}]", _dt.now().isoformat(timespec='seconds'), aid)
                        )
                        conn2.commit()
                        conn2.close()
                        _log_retry(f"#{aid} ❌ {res['error']}")
                        # 失败后短暂延迟，不给源站点压力
                        time.sleep(random.uniform(2, 5))
                        return {"status": "fail", "aid": aid, "error": res['error']}

                    # ── 成功 — 入库 ──
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
                    conn2.commit()
                    conn2.close()
                    _log_retry(f"#{aid} ✅ 缓存成功 [{lang}] {len(html)//1024}KB")

                    # 成功后同源延迟 5-10s
                    time.sleep(random.uniform(5, 10))
                    return {"status": "ok", "aid": aid, "lang": lang, "size_kb": len(html)//1024}

                except Exception as e:
                    _log_retry(f"#{aid} ❌ {str(e)[:300]}")
                    time.sleep(random.uniform(2, 5))
                    return {"status": "fail", "aid": aid, "error": str(e)[:300]}

        # ── 提交到线程池 ──
        with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
            futures = {executor.submit(_do_retry_one, a): a for a in to_retry}
            for future in as_completed(futures):
                if _retry_state.get("cancelled"):
                    # 尝试取消尚未开始的 future
                    for f in futures:
                        f.cancel()
                try:
                    r = future.result()
                except Exception:
                    r = {"status": "fail", "aid": 0, "error": "worker 异常"}
                if r.get("status") == "fail":
                    _retry_state["failed"] += 1
                _retry_state["done"] += 1

        _retry_state["running"] = False
        _retry_state["current"] = "完成"
        _log_retry(f"🏁 批量重试完成 — 成功 {_retry_state['done'] - _retry_state['failed']}/{_retry_state['done']}，失败 {_retry_state['failed']}，跳过 {skipped}")

    threading.Thread(target=_batch_retry, daemon=True).start()
    return {
        "ok": True, "total": len(ids), "skipped": 0,  # skipped 在 _batch_retry 启动后更新
        "message": f"开始批量重试（{_WORKERS} 线程并行，同源间隔 5-10 秒）"
    }


@router.get("/articles/batch-retry/status")
def batch_retry_status():
    """查询批量重试进度 — 含耗时、跳过数。"""
    s = dict(_retry_state)
    if s.get("started_at"):
        try:
            started = datetime.fromisoformat(s["started_at"])
            s["elapsed_seconds"] = int((datetime.now() - started).total_seconds())
        except (ValueError, TypeError):
            s["elapsed_seconds"] = 0
    return s


@router.post("/articles/batch-retry/cancel")
def batch_retry_cancel():
    """取消当前批量重试任务 — 已开始的 worker 会完成，未开始的跳过。"""
    global _retry_state
    if not _retry_state.get("running"):
        return {"ok": False, "message": "没有正在运行的重试任务"}
    _retry_state["cancelled"] = True
    _log_retry("🛑 收到取消请求 — 正在停止...")
    return {"ok": True, "message": "重试任务已取消（已开始的 worker 会完成当前文章）"}


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


# ══════════════════════════════════════════════════════════════
# 调度管理
# ══════════════════════════════════════════════════════════════

@router.get("/schedule")
def get_schedule():
    """获取当前调度配置和状态。"""
    return get_schedule_info()


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    hours: list[int] | None = None
    minutes: list[int] | None = None
    # AI 全流程调度
    ai_enabled: bool | None = None
    ai_hours: list[int] | None = None
    ai_minutes: list[int] | None = None


@router.put("/schedule")
def update_schedule(body: ScheduleUpdate):
    """更新调度配置并重载调度器。"""
    if body.hours is not None:
        if not isinstance(body.hours, list) or len(body.hours) == 0:
            raise HTTPException(400, "hours 必须是非空整数列表")
        if len(body.hours) > 48:
            raise HTTPException(400, "最多支持 48 个定时时间")
        for h in body.hours:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise HTTPException(400, f"小时值无效: {h}（应为 0-23）")
        config.pipeline_cron_hours = body.hours

    if body.minutes is not None:
        if not isinstance(body.minutes, list):
            raise HTTPException(400, "minutes 必须是整数列表")
        for m in body.minutes:
            if not isinstance(m, int) or m < 0 or m > 59:
                raise HTTPException(400, f"分钟值无效: {m}（应为 0-59）")
        config.pipeline_cron_minutes = body.minutes

    if body.enabled is not None:
        config.pipeline_schedule_enabled = body.enabled

    if body.ai_enabled is not None:
        config.ai_cron_enabled = body.ai_enabled

    if body.ai_hours is not None:
        if not isinstance(body.ai_hours, list) or len(body.ai_hours) == 0:
            raise HTTPException(400, "ai_hours 必须是非空整数列表")
        if len(body.ai_hours) > 48:
            raise HTTPException(400, "最多支持 48 个 AI 定时时间")
        for h in body.ai_hours:
            if not isinstance(h, int) or h < 0 or h > 23:
                raise HTTPException(400, f"AI 小时值无效: {h}（应为 0-23）")
        config.ai_cron_hours = body.ai_hours

    if body.ai_minutes is not None:
        if not isinstance(body.ai_minutes, list):
            raise HTTPException(400, "ai_minutes 必须是整数列表")
        for m in body.ai_minutes:
            if not isinstance(m, int) or m < 0 or m > 59:
                raise HTTPException(400, f"AI 分钟值无效: {m}（应为 0-59）")
        config.ai_cron_minutes = body.ai_minutes

    # 重载调度器
    try:
        reload_scheduler()
    except Exception as e:
        raise HTTPException(500, f"调度器重载失败: {str(e)[:200]}")

    return get_schedule_info()


class ToggleSchedule(BaseModel):
    enabled: bool


@router.post("/schedule/toggle")
def toggle_schedule(body: ToggleSchedule):
    """快速启用/禁用调度。"""
    config.pipeline_schedule_enabled = body.enabled
    try:
        reload_scheduler()
    except Exception as e:
        raise HTTPException(500, f"调度器重载失败: {str(e)[:200]}")

    return {
        'ok': True,
        'enabled': body.enabled,
        'message': '调度已启用' if body.enabled else '调度已禁用',
    }


@router.get("/schedule/logs")
def schedule_logs(limit: int = Query(50, ge=1, le=100)):
    """获取调度器日志。"""
    return {'logs': get_schedule_logs(limit)}


# ── 内部工具 ──────────────────────────────────────────────

def _log_retry(msg: str):
    global _retry_state
    ts = datetime.now().strftime('%H:%M:%S')
    _retry_state["log"].append(f"[{ts}] {msg}")
