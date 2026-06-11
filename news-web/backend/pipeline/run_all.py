"""
Pipeline orchestrator — runs the full fetch → cluster → analyze cycle.
Replaces cron_runner.sh / Hermes/OpenClaw scheduling.
Call via `run_pipeline(db_path, user_agent)` or `python -m backend.pipeline.run_all`.
"""
import os, sys, subprocess, logging

logger = logging.getLogger(__name__)

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_pipeline(db_path: str = "", user_agent: str = "", callback=None):
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
        ('fetch_content.py', '页面归档'),
    ]

    # Step 3.5: AI 翻译 (only if translation enabled + API key)
    from config import config
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

        result = subprocess.run(
            [sys.executable, script_path],
            env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=300,
        )

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
