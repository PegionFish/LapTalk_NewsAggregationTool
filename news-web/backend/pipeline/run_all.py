"""
Pipeline orchestrator — runs the full fetch → cluster → analyze cycle.
Replaces cron_runner.sh / Hermes/OpenClaw scheduling.
Call via `run_pipeline(db_path, user_agent)` or `python -m backend.pipeline.run_all`.
"""
import os, sys, subprocess, logging

logger = logging.getLogger(__name__)

# 各步骤超时时间（秒）— fetch_content 需要下载大量页面，超时更长
STEP_TIMEOUTS = {
    'fetch_english_news.py': 300,
    'fetch_platform_hotlists.py': 300,
    'collect_data.py': 300,
    'ai_filter.py': 600,
    'fetch_content.py': 900,
    'translate_content.py': 600,
    'analyze.py': 600,
}

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_pipeline(db_path: str = "", user_agent: str = "", callback=None, run_type: str = 'scheduled'):
    """
    Execute the full pipeline sequence:
    1. fetch_english_news.py — RSS feeds
    2. collect_data.py — dedup, cluster, save to DB
    3. fetch_content.py — archive pages (optional)
    4. AI analysis (if API configured)

    Args:
        db_path: SQLite database path (injects into subprocess env)
        user_agent: UA for fetch scripts
        callback: optional function(status, step) for progress reporting
    """
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'  # 子进程 UTF-8 输出兼容
    if db_path:
        env['NEWS_DB_PATH'] = db_path
    if user_agent:
        env['USER_AGENT'] = user_agent

    steps = [
        ('fetch_english_news.py', 'RSS 抓取'),
    ]

    # 平台热搜采集 — 可配置开关
    from config import config as _cfg
    if _cfg.platform_hotlist_enabled:
        env['BILIBILI_MAX_PAGES'] = str(_cfg.bilibili_max_pages)
        steps.append(('fetch_platform_hotlists.py', '平台热搜'))

    steps += [
        ('collect_data.py', '去重聚类'),
    ]

    # AI 预筛选 — 只在有 API Key 时启用，筛掉不需要的文章再下载
    from config import config
    if config.openai_api_key:
        steps.append(('ai_filter.py', 'AI 筛选'))

    steps.append(('fetch_content.py', '页面归档'))
    if config.translation_enabled and config.translation_api_key:
        steps.append(('translate_content.py', 'AI 翻译'))

    # Step 4: AI analysis (only if API key is configured)
    if config.openai_api_key:
        steps.append(('analyze.py', 'AI 分析'))

    for script, label in steps:
        script_path = os.path.join(PIPELINE_DIR, script)
        if not os.path.exists(script_path):
            logger.warning(f"[Pipeline] {label}: 脚本不存在 ({script_path}) — 跳过")
            if callback:
                callback('skipped', f"{label}: 脚本不存在")
            continue

        logger.info(f"[Pipeline] {label}...")
        if callback:
            callback('running', label)

        timeout = STEP_TIMEOUTS.get(script, 300)
        result = subprocess.run(
            [sys.executable, script_path],
            env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
        )

        # ── 记录 fetch_logs（仅抓取类步骤） ─────────────
        if script in ('fetch_english_news.py', 'fetch_platform_hotlists.py') and db_path:
            try:
                from datetime import datetime as _dt
                from db.news_db import NewsDB as _NDB_
                _ndb2 = _NDB_(db_path)
                status = 'ok' if result.returncode == 0 else 'failed'
                error_msg = result.stderr[:200] if result.returncode != 0 else ''
                out = result.stdout or ''
                import re as _re3
                fm = _re3.search(r'总条目[：:]\s*(\d+)', out)
                fetched = int(fm.group(1)) if fm else 0
                source_name = 'RSS' if script == 'fetch_english_news.py' else '平台热搜'
                source_type = 'rss' if script == 'fetch_english_news.py' else 'hotlist'
                _ndb2.log_fetch(source_name, source_type, fetched, 0, status, error_msg, 0, run_type)
            except Exception as _fe:
                logger.warning(f"fetch_logs write failed: {_fe}")

        if result.returncode != 0:
            logger.error(f"[Pipeline] {label} 失败: {result.stderr[:200]}")
            if callback:
                callback('error', f"{label}: {result.stderr[:100]}")
            return False

        logger.info(f"[Pipeline] {label} 完成")

    if callback:
        callback('complete', '全部完成')
    return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    success = run_pipeline()
    sys.exit(0 if success else 1)
