"""
Pipeline orchestrator — runs the full fetch → cluster → analyze cycle.
Streams subprocess stdout in real-time for detailed progress reporting.
"""
import os, sys, subprocess, logging, re

logger = logging.getLogger(__name__)

STEP_TIMEOUTS = {
    'fetch_english_news.py': 300,
    'fetch_platform_hotlists.py': 300,
    'collect_data.py': 300,
    'fetch_content.py': 1800,
    'translate_content.py': 900,
    'analyze.py': 900,
    'browser_capture.py': 600,
}

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))


def _stream_process(proc, callback, label):
    """流式读取子进程 stdout，实时回调每行输出。"""
    output_lines = []
    for raw_line in iter(proc.stdout.readline, ''):
        line = raw_line.rstrip('\n').rstrip('\r')
        if not line:
            continue
        output_lines.append(line)
        # 过滤有意义的进度行（跳过空行和纯格式行）
        clean = line.strip()
        if clean and not clean.startswith('---') and not clean.startswith('==='):
            callback('running', f"[{label}] {clean}")
    proc.stdout.close()
    proc.wait()
    return '\n'.join(output_lines)


def run_pipeline(db_path: str = "", user_agent: str = "", callback=None, run_type: str = 'scheduled'):
    """
    Execute the full pipeline with real-time progress streaming.

    Args:
        db_path: SQLite database path
        user_agent: UA for fetch scripts
        callback: function(status, message) for progress reporting
    """
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    if db_path:
        env['NEWS_DB_PATH'] = db_path
    if user_agent:
        env['USER_AGENT'] = user_agent

    steps = [('fetch_english_news.py', 'RSS 抓取')]

    from config import config as _cfg
    if _cfg.platform_hotlist_enabled:
        env['BILIBILI_MAX_PAGES'] = str(_cfg.bilibili_max_pages)
        steps.append(('fetch_platform_hotlists.py', '平台热搜'))

    steps.append(('collect_data.py', '去重聚类'))

    from config import config
    steps.append(('fetch_content.py', '页面归档'))
    if config.translation_enabled and config.translation_api_key:
        steps.append(('translate_content.py', 'AI 翻译'))

    if config.openai_api_key:
        steps.append(('analyze.py', 'AI 分析'))

    # 浏览器渲染兜底 — 对 HTTP 无法获取的文章使用 Playwright 重试
    steps.append(('browser_capture.py', '浏览器渲染兜底'))

    for idx, (script, label) in enumerate(steps, 1):
        script_path = os.path.join(PIPELINE_DIR, script)
        if not os.path.exists(script_path):
            logger.warning(f"[Pipeline] {label}: script not found — skipped")
            if callback:
                callback('skipped', f"[{label}] 脚本不存在，跳过")
            continue

        progress = f"[{idx}/{len(steps)}]"
        logger.info(f"[Pipeline] {label}...")
        if callback:
            callback('running', f"{progress} {label} 启动中...")

        timeout = STEP_TIMEOUTS.get(script, 300)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-u', script_path],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding='utf-8', errors='replace',
            )
            full_output = _stream_process(proc, callback, label)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error(f"[Pipeline] {label} timed out ({timeout}s)")
            if callback:
                callback('error', f"{progress} {label} 超时 ({timeout}s)")
            return False
        except Exception as e:
            logger.error(f"[Pipeline] {label} exception: {e}")
            if callback:
                callback('error', f"{progress} {label} 异常: {str(e)[:100]}")
            return False

        # 记录 fetch_logs
        if script in ('fetch_english_news.py', 'fetch_platform_hotlists.py') and db_path:
            try:
                from datetime import datetime as _dt
                from db.news_db import NewsDB as _NDB_
                _ndb2 = _NDB_(db_path)
                status = 'ok' if proc.returncode == 0 else 'failed'
                error_msg = ''
                stderr_out = ''
                try:
                    stderr_out = proc.stderr.read() if proc.stderr else ''
                except Exception:
                    pass
                if proc.returncode != 0:
                    error_msg = stderr_out[:200]
                fm = re.search(r'总条目[：:]\s*(\d+)', full_output or '')
                fetched = int(fm.group(1)) if fm else 0
                source_name = 'RSS' if script == 'fetch_english_news.py' else '平台热搜'
                source_type = 'rss' if script == 'fetch_english_news.py' else 'hotlist'
                _ndb2.log_fetch(source_name, source_type, fetched, 0, status, error_msg, 0, run_type)
            except Exception as _fe:
                logger.warning(f"fetch_logs write failed: {_fe}")

        if proc.returncode != 0:
            logger.error(f"[Pipeline] {label} failed (exit {proc.returncode})")
            stderr_msg = ''
            try:
                stderr_msg = proc.stderr.read()[:100] if proc.stderr else ''
            except Exception:
                pass
            if callback:
                callback('error', f"{progress} {label} 失败: {stderr_msg}")
            return False

        logger.info(f"[Pipeline] {label} done")
        if callback:
            callback('running', f"{progress} {label} 完成")

    if callback:
        callback('complete', '全部完成')

    # Pipeline 完成后，回填所有文章的 topic_category
    if db_path:
        try:
            from db.news_db import NewsDB as _NDB3
            _ndb3 = _NDB3(db_path)
            updated = _ndb3.populate_topic_categories()
            if updated and callback:
                callback('running', f"主题分类回填: {updated} 篇文章")
        except Exception as _tce:
            logger.warning(f"topic_category populate failed: {_tce}")

    return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    success = run_pipeline()
    sys.exit(0 if success else 1)
