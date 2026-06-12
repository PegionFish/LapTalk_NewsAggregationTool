"""
缓存状态检查 API — 诊断本地内容缓存的完整性。
"""
import os, sqlite3, threading
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks

from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/cache", tags=["cache"])

# 热榜排除过滤条件
_HOTLIST_EXCLUDE = "category NOT IN ('platform_hotlists', 'bilibili_videos')"

# 缓存抓取状态
_cache_fetch_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}


def _get_conn():
    if not config.db_path:
        return None
    return sqlite3.connect(config.db_path)


def _scan_cache_dir() -> set:
    """扫描磁盘缓存目录，返回已有的 article ID 集合（不含 ERR 标记项）。"""
    cached = set()
    cache_dir = config.content_cache_path
    if not os.path.isdir(cache_dir):
        return cached
    for fname in os.listdir(cache_dir):
        if fname.endswith('.html') and fname[0].isdigit():
            try:
                cached.add(int(fname.split('.')[0]))
            except ValueError:
                pass
    return cached


@router.get("/status")
def cache_status():
    """检查内容缓存状态 — 仅统计 RSS 新闻，排除热榜。"""
    conn = _get_conn()
    if not conn:
        return {'error': 'database_not_configured'}

    total = conn.execute(f"SELECT COUNT(*) FROM articles WHERE {_HOTLIST_EXCLUDE}").fetchone()[0]
    with_url = conn.execute(f"SELECT COUNT(*) FROM articles WHERE url != '' AND url LIKE 'http%' AND {_HOTLIST_EXCLUDE}").fetchone()[0]
    with_local = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%' AND {_HOTLIST_EXCLUDE}"
    ).fetchone()[0]
    with_err = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%' AND {_HOTLIST_EXCLUDE}"
    ).fetchone()[0]
    pending = total - with_local - with_err
    with_text = conn.execute(f"SELECT COUNT(*) FROM articles WHERE text_content != '' AND {_HOTLIST_EXCLUDE}").fetchone()[0]
    with_translation = conn.execute(f"SELECT COUNT(*) FROM articles WHERE translated_content != '' AND {_HOTLIST_EXCLUDE}").fetchone()[0]
    en_articles = conn.execute(f"SELECT COUNT(*) FROM articles WHERE content_lang='en' AND {_HOTLIST_EXCLUDE}").fetchone()[0]

    # 磁盘文件统计
    disk_ids = _scan_cache_dir()
    disk_count = len(disk_ids)

    # 交叉比对：DB 有记录但磁盘文件缺失
    db_ids = set()
    for (row,) in conn.execute(f"SELECT id FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%' AND {_HOTLIST_EXCLUDE}"):
        db_ids.add(row)
    missing_on_disk = sorted(db_ids - disk_ids)
    orphan_files = sorted(disk_ids - db_ids)

    # 未缓存的文章列表（有 URL 但无 local_path）
    uncached_total = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE url != '' AND url LIKE 'http%' "
        f"AND (local_path = '' OR local_path IS NULL) AND {_HOTLIST_EXCLUDE}"
    ).fetchone()[0]
    uncached_rows = conn.execute(
        f"SELECT id, title, source FROM articles WHERE url != '' AND url LIKE 'http%' "
        f"AND (local_path = '' OR local_path IS NULL) AND {_HOTLIST_EXCLUDE} "
        f"ORDER BY id DESC LIMIT 100"
    ).fetchall()

    # 最近下载
    recent = conn.execute(
        f"SELECT id, title, source, content_fetched_at FROM articles "
        f"WHERE content_fetched_at IS NOT NULL AND {_HOTLIST_EXCLUDE} "
        f"ORDER BY content_fetched_at DESC LIMIT 10"
    ).fetchall()

    conn.close()

    return {
        'checked_at': datetime.utcnow().isoformat(timespec='seconds'),
        'cache_dir': config.content_cache_path,
        'summary': {
            'total_articles': total,
            'with_url': with_url,
            'cached_db': with_local,
            'cached_disk': disk_count,
            'missing_disk': len(missing_on_disk),
            'orphan_files': len(orphan_files),
            'with_text': with_text,
            'with_translation': with_translation,
            'pending_download': pending,
            'failed_download': with_err,
            'en_articles': en_articles,
        },
        'recent': [
            {'id': r[0], 'title': r[1][:60], 'source': r[2], 'fetched_at': r[3]}
            for r in recent
        ],
        'missing_on_disk': missing_on_disk[:50],
        'orphan_files': orphan_files[:50],
        'uncached_articles': [
            {'id': r[0], 'title': r[1][:80], 'source': r[2]}
            for r in uncached_rows
        ],
        'uncached_count': uncached_total,
    }


def _batch_cache_fetch():
    """后台线程：批量抓取未缓存的文章。"""
    global _cache_fetch_state
    _cache_fetch_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        from pipeline.fetch_content import fetch_article_content
        conn = _get_conn()
        if not conn:
            return
        rows = conn.execute(
            f"SELECT id, title, url FROM articles WHERE url != '' AND url LIKE 'http%' "
            f"AND (local_path = '' OR local_path IS NULL) AND {_HOTLIST_EXCLUDE} "
            f"ORDER BY id DESC"
        ).fetchall()
        conn.close()

        if not rows:
            _cache_fetch_state["running"] = False
            return

        _cache_fetch_state["total"] = len(rows)
        _cache_fetch_state["log"].append(f"开始抓取 {len(rows)} 篇未缓存文章")

        for idx, (aid, title, url) in enumerate(rows, 1):
            _cache_fetch_state["current"] = f"#{aid} {title[:50]}"
            try:
                result = fetch_article_content(url, aid)
                if result and result.get('local_path'):
                    _cache_fetch_state["done"] += 1
                    _cache_fetch_state["log"].append(f"#{aid} ✅ {title[:40]}")
                else:
                    _cache_fetch_state["failed"] += 1
                    _cache_fetch_state["log"].append(f"#{aid} ❌ {title[:40]}")
            except Exception as e:
                _cache_fetch_state["failed"] += 1
                _cache_fetch_state["log"].append(f"#{aid} ❌ {str(e)[:60]}")
    except Exception as e:
        _cache_fetch_state["log"].append(f"错误: {str(e)[:100]}")
    finally:
        _cache_fetch_state["running"] = False


@router.get("/fetch/status")
def get_cache_fetch_status():
    """查询缓存抓取进度。"""
    return dict(_cache_fetch_state)


@router.post("/fetch/start")
def start_cache_fetch():
    """启动批量缓存抓取。"""
    if _cache_fetch_state.get("running"):
        return {"ok": False, "message": "抓取任务已在运行中"}
    _cache_fetch_state["log"] = []
    threading.Thread(target=_batch_cache_fetch, daemon=True).start()
    return {"ok": True, "message": "开始抓取未缓存文章"}


@router.post("/verify")
def verify_content(background_tasks: BackgroundTasks):
    """验证所有缓存文件可读性（异步后台任务）。
    立即返回，后台逐文件校验，结果写入日志。"""
    import logging
    logger = logging.getLogger(__name__)

    cache_dir = config.content_cache_path
    if not os.path.isdir(cache_dir):
        return {'ok': False, 'message': '缓存目录不存在'}

    files = [f for f in os.listdir(cache_dir) if f.endswith('.html')]
    if not files:
        return {'ok': True, 'message': '无缓存文件需要校验', 'total': 0}

    def verify_all():
        ok = err = 0
        for fname in files:
            fpath = os.path.join(cache_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                if len(content) > 100:
                    ok += 1
                else:
                    logger.warning(f"缓存文件过小: {fname} ({len(content)} 字节)")
                    err += 1
            except Exception as e:
                logger.error(f"缓存文件损坏: {fname} — {e}")
                err += 1
        logger.info(f"缓存校验完成: {ok} 正常, {err} 异常")

    background_tasks.add_task(verify_all)
    return {'ok': True, 'message': f'开始校验 {len(files)} 个缓存文件，结果将记录在日志中', 'total': len(files)}


@router.delete("/orphan")
def clean_orphan_files():
    """清理磁盘上无对应 DB 记录的孤立缓存文件。"""
    cache_dir = config.content_cache_path
    if not os.path.isdir(cache_dir):
        return {'ok': False, 'message': '缓存目录不存在'}

    conn = _get_conn()
    if not conn:
        return {'error': 'database_not_configured'}
    db_ids = set()
    for (row,) in conn.execute("SELECT id FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'"):
        db_ids.add(row)
    conn.close()

    removed = 0
    for fname in os.listdir(cache_dir):
        if fname.endswith('.html') and fname[0].isdigit():
            aid = int(fname.split('.')[0])
            if aid not in db_ids:
                os.remove(os.path.join(cache_dir, fname))
                removed += 1

    return {'ok': True, 'removed': removed, 'message': f'清理了 {removed} 个孤立缓存文件'}
