"""
缓存状态检查 API — 诊断本地内容缓存的完整性。
"""
import os, sqlite3
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks

from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/cache", tags=["cache"])


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
    """检查内容缓存状态 — 统计磁盘/DB/URL 各维度。"""
    conn = _get_conn()
    if not conn:
        return {'error': 'database_not_configured'}

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    with_url = conn.execute("SELECT COUNT(*) FROM articles WHERE url != '' AND url LIKE 'http%'").fetchone()[0]
    with_local = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'"
    ).fetchone()[0]
    with_err = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'"
    ).fetchone()[0]
    pending = total - with_local - with_err  # 从未尝试下载
    with_text = conn.execute("SELECT COUNT(*) FROM articles WHERE text_content != ''").fetchone()[0]
    with_translation = conn.execute("SELECT COUNT(*) FROM articles WHERE translated_content != ''").fetchone()[0]
    en_articles = conn.execute("SELECT COUNT(*) FROM articles WHERE content_lang='en'").fetchone()[0]

    # 磁盘文件统计
    disk_ids = _scan_cache_dir()
    disk_count = len(disk_ids)

    # 交叉比对：DB 有记录但磁盘文件缺失
    db_ids = set()
    for (row,) in conn.execute("SELECT id FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'"):
        db_ids.add(row)
    missing_on_disk = sorted(db_ids - disk_ids)
    orphan_files = sorted(disk_ids - db_ids)

    # 最近下载
    recent = conn.execute(
        "SELECT id, title, source, content_fetched_at FROM articles "
        "WHERE content_fetched_at IS NOT NULL ORDER BY content_fetched_at DESC LIMIT 10"
    ).fetchall()

    conn.close()

    return {
        'checked_at': datetime.utcnow().isoformat(timespec='seconds'),
        'cache_dir': config.content_cache_path,
        'summary': {
            'total_articles': total,
            'with_url': with_url,
            'cached_db': with_local,           # DB 有 local_path 记录
            'cached_disk': disk_count,         # 磁盘文件实际存在
            'missing_disk': len(missing_on_disk),     # DB 有记录但文件缺失
            'orphan_files': len(orphan_files),        # 磁盘有文件但 DB 无记录
            'with_text': with_text,            # 纯文本已提取
            'with_translation': with_translation,     # 翻译已完成
            'pending_download': pending,       # 从未尝试下载
            'failed_download': with_err,       # 下载失败
            'en_articles': en_articles,        # 英文文章（可翻译）
        },
        'recent': [
            {'id': r[0], 'title': r[1][:60], 'source': r[2], 'fetched_at': r[3]}
            for r in recent
        ],
        'missing_on_disk': missing_on_disk[:50],   # 只返回前 50 个
        'orphan_files': orphan_files[:50],
    }


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
