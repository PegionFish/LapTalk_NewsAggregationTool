"""
APScheduler-based pipeline scheduler.
Runs the news pipeline at configurable times daily (default 10:00 / 17:00).
Can be toggled on/off and schedule changed via config/API.
"""
import os, sqlite3, logging, glob, time, asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from pipeline.run_all import run_pipeline
from api.pipeline_event import _nightly
from utils.task_lock import task_lock
from utils.task_state import task_state

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# ── Pipeline status tracking ─────────────────────────────
_pipeline_state = {
    'running': False,
    'last_run': None,
    'last_status': None,
    'current_step': None,
    'steps': [],
    'run_type': 'scheduled',
}

# ── 事件管线状态追踪 ─────────────────────────────
_ai_full_state = {
    'running': False,
    'last_run': None,
    'last_status': None,
}

# 调度器日志（内存环形缓冲）
_schedule_log: list[str] = []
def _add_schedule_log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _schedule_log.append(f"[{ts}] {msg}")


def get_pipeline_status() -> dict:
    """Return current pipeline status (called by GET /api/pipeline/status)."""
    return dict(_pipeline_state)


def get_schedule_info() -> dict:
    """返回当前调度配置和状态（含事件管线）。"""
    hours = config.pipeline_cron_hours
    minutes = config.pipeline_cron_minutes
    while len(minutes) < len(hours):
        minutes.append(0)
    schedule = []
    for i, h in enumerate(hours[:len(minutes)]):
        schedule.append({'hour': h, 'minute': minutes[i]})

    ai_hours = config.ai_cron_hours
    ai_minutes = config.ai_cron_minutes
    while len(ai_minutes) < len(ai_hours):
        ai_minutes.append(0)
    ai_schedule = []
    for i, h in enumerate(ai_hours[:len(ai_minutes)]):
        ai_schedule.append({'hour': h, 'minute': ai_minutes[i]})

    return {
        'enabled': config.pipeline_schedule_enabled,
        'schedule': schedule,
        'ai_enabled': config.ai_cron_enabled,
        'ai_schedule': ai_schedule,
        'scheduler_running': scheduler.running,
        'last_run': _pipeline_state.get('last_run'),
        'last_status': _pipeline_state.get('last_status'),
        'ai_last_run': _ai_full_state.get('last_run'),
        'ai_last_status': _ai_full_state.get('last_status'),
    }


def get_schedule_logs(limit: int = 50) -> list[str]:
    """返回调度器日志。"""
    return _schedule_log[-limit:]


def _build_cron_triggers() -> list[CronTrigger]:
    """根据配置生成 cron triggers。"""
    hours = config.pipeline_cron_hours
    minutes = config.pipeline_cron_minutes
    while len(minutes) < len(hours):
        minutes.append(0)
    triggers = []
    for i, h in enumerate(hours[:len(minutes)]):
        triggers.append(CronTrigger(hour=h, minute=minutes[i]))
    return triggers


def _build_ai_cron_triggers() -> list[CronTrigger]:
    """根据配置生成 事件管线 cron triggers。"""
    hours = config.ai_cron_hours
    minutes = config.ai_cron_minutes
    while len(minutes) < len(hours):
        minutes.append(0)
    triggers = []
    for i, h in enumerate(hours[:len(minutes)]):
        triggers.append(CronTrigger(hour=h, minute=minutes[i]))
    return triggers


async def _run_pipeline_job():
    """Wrapper that runs pipeline in thread to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_pipeline_job_sync)


# ── SQLite backup (daily 03:00, keep 7 days) ─────────────
async def _backup_db():
    """VACUUM INTO a date-stamped backup, prune older than 7 days."""
    if not config.db_path or not os.path.exists(config.db_path):
        logger.warning("Backup skipped: db_path not configured or file missing")
        return
    import shutil
    backup_dir = os.path.join(os.path.dirname(config.db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d')
    backup_path = os.path.join(backup_dir, f'news.db.backup.{stamp}')
    conn = sqlite3.connect(config.db_path)
    try:
        conn.execute("VACUUM INTO ?", (backup_path,))
        logger.info(f"Database backed up to {backup_path}")
    except sqlite3.OperationalError as e:
        logger.warning(f"VACUUM INTO not supported on this SQLite version, using file copy: {e}")
        shutil.copy2(config.db_path, backup_path)
    finally:
        conn.close()
    # Prune backups older than 7 days
    cutoff = time.time() - 7 * 86400
    for f in glob.glob(os.path.join(backup_dir, 'news.db.backup.*')):
        if os.path.getmtime(f) < cutoff:
            os.remove(f)
            logger.info(f"Pruned old backup: {f}")

    # 审计日志轮转
    try:
        from api.dashboard import rotate_audit_log
        rotate_audit_log()
    except Exception as e:
        logger.warning(f"审计日志轮转失败: {e}")


def start_scheduler():
    """Start scheduler if any schedule is enabled in config."""
    pipeline_enabled = config.pipeline_schedule_enabled
    ai_enabled = config.ai_cron_enabled

    if not pipeline_enabled and not ai_enabled:
        _add_schedule_log("调度器已禁用（管道和 AI 定时均未启用）")
        logger.info("Scheduler is fully disabled in config")
        return

    if not scheduler.running:
        # 数据采集管道
        if pipeline_enabled:
            triggers = _build_cron_triggers()
            for trigger in triggers:
                scheduler.add_job(_run_pipeline_job, trigger)
        # 事件管线
        if ai_enabled:
            ai_triggers = _build_ai_cron_triggers()
            for trigger in ai_triggers:
                scheduler.add_job(_run_ai_full_job, trigger)
        # Daily backup at 03:00
        scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0))
        # pending_cluster 批处理每天 02:30
        scheduler.add_job(_run_pending_cluster_job, CronTrigger(hour=2, minute=30))
        scheduler.start()

        parts = []
        if pipeline_enabled:
            hours = config.pipeline_cron_hours
            minutes = config.pipeline_cron_minutes
            while len(minutes) < len(hours):
                minutes.append(0)
            time_strs = [f"{h:02d}:{minutes[i]:02d}" for i, h in enumerate(hours[:len(minutes)])]
            parts.append("管道 " + ", ".join(time_strs))
        if ai_enabled:
            ai_hours = config.ai_cron_hours
            ai_minutes = config.ai_cron_minutes
            while len(ai_minutes) < len(ai_hours):
                ai_minutes.append(0)
            ai_strs = [f"{h:02d}:{ai_minutes[i]:02d}" for i, h in enumerate(ai_hours[:len(ai_minutes)])]
            parts.append("事件管线 " + ", ".join(ai_strs))
        parts.append("pending_cluster 02:30")
        _add_schedule_log("调度器启动: " + " / ".join(parts))
        logger.info(f"Scheduler started: {' / '.join(parts)}, backup at 03:00, pending_cluster at 02:30")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        _add_schedule_log("调度器已停止")
        logger.info("Pipeline scheduler stopped")


def reload_scheduler():
    """动态重载调度器 — 停止旧任务，根据新配置重新添加。"""
    global scheduler
    import asyncio

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped for reload")

    scheduler = BackgroundScheduler()

    pipeline_enabled = config.pipeline_schedule_enabled
    ai_enabled = config.ai_cron_enabled

    if not pipeline_enabled and not ai_enabled:
        _add_schedule_log("调度器重载: 已禁用（管道和 AI 均未启用）")
        logger.info("Scheduler reload: fully disabled in config")
        return

    if pipeline_enabled:
        triggers = _build_cron_triggers()
        for trigger in triggers:
            scheduler.add_job(_run_pipeline_job, trigger)
    if ai_enabled:
        ai_triggers = _build_ai_cron_triggers()
        for trigger in ai_triggers:
            scheduler.add_job(_run_ai_full_job, trigger)
    scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0))
    # pending_cluster 批处理每天 02:30
    scheduler.add_job(_run_pending_cluster_job, CronTrigger(hour=2, minute=30))

    scheduler.start()

    parts = []
    if pipeline_enabled:
        hours = config.pipeline_cron_hours
        minutes = config.pipeline_cron_minutes
        while len(minutes) < len(hours):
            minutes.append(0)
        time_strs = [f"{h:02d}:{minutes[i]:02d}" for i, h in enumerate(hours[:len(minutes)])]
        parts.append("管道 " + ", ".join(time_strs))
    if ai_enabled:
        ai_hours = config.ai_cron_hours
        ai_minutes = config.ai_cron_minutes
        while len(ai_minutes) < len(ai_hours):
            ai_minutes.append(0)
        ai_strs = [f"{h:02d}:{ai_minutes[i]:02d}" for i, h in enumerate(ai_hours[:len(ai_minutes)])]
        parts.append("事件管线 " + ", ".join(ai_strs))
    parts.append("pending_cluster 02:30")
    _add_schedule_log("调度器重载: " + " / ".join(parts))
    logger.info(f"Scheduler reloaded: {' / '.join(parts)}")


async def trigger_pipeline_manual():
    """Manually trigger a pipeline run (via API)."""
    global _pipeline_state
    _pipeline_state['run_type'] = 'manual'
    _add_schedule_log("手动触发管道")
    import concurrent.futures
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_pipeline_job_sync)
    return {'status': 'pipeline_started'}


def _run_pipeline_job_sync():
    """同步版本的管道执行（在线程池中运行）。"""
    global _pipeline_state

    ok, reason = task_lock.acquire('pipeline')
    if not ok:
        _add_schedule_log(f"管道启动失败: {reason}")
        logger.warning(f"Pipeline skipped: {reason}")
        return

    task_state.init_state('pipeline')
    _pipeline_state.update(running=True, current_step='starting', steps=[])
    _add_schedule_log("管道启动")
    logger.info("Pipeline starting...")
    try:
        def progress_callback(status, message):
            _pipeline_state['current_step'] = message
            _pipeline_state['steps'].append({'name': message, 'status': status, 'duration_ms': 0})
            task_state.update('pipeline', current=message, log_msg=message)
            _add_schedule_log(f"[pipeline] {message}")

        success = run_pipeline(
            db_path=config.db_path,
            user_agent=config.user_agent,
            callback=progress_callback,
            run_type=_pipeline_state.get('run_type', 'scheduled'),
        )
        _pipeline_state['last_status'] = 'success' if success else 'failed'
        if success:
            _add_schedule_log("管道执行成功")
            logger.info("Pipeline completed successfully")
            task_state.finish('pipeline', success=True)
        else:
            _add_schedule_log("管道执行失败")
            logger.error("Pipeline failed")
            task_state.finish('pipeline', success=False, error="Pipeline failed")
    except Exception as e:
        _pipeline_state['last_status'] = 'error'
        _add_schedule_log(f"管道异常: {str(e)[:100]}")
        logger.exception(f"Pipeline error: {e}")
        task_state.finish('pipeline', success=False, error=str(e)[:200])
    finally:
        _pipeline_state['running'] = False
        _pipeline_state['run_type'] = 'scheduled'
        _pipeline_state['last_run'] = datetime.now().isoformat(timespec='seconds')
        task_lock.release('pipeline')


# ══════════════════════════════════════════════════════════
# 事件管线定时任务
# ══════════════════════════════════════════════════════════

async def _run_ai_full_job():
    """Wrapper that runs AI full in thread to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_ai_full_job_sync)


def _run_ai_full_job_sync():
    """同步版本的事件管线执行（在线程池中运行）。"""
    global _ai_full_state

    ok, reason = task_lock.acquire('event')
    if not ok:
        _add_schedule_log(f"事件管线启动失败: {reason}")
        logger.warning(f"Event pipeline skipped: {reason}")
        return

    _ai_full_state.update(running=True)
    _add_schedule_log("事件管线启动（聚类→摘要→逻辑链）")
    logger.info("Event pipeline starting...")
    try:
        _nightly()
        # _nightly() 在其 finally 块中调用 task_lock.release('event')
        _ai_full_state['last_status'] = 'success'
        _add_schedule_log("事件管线执行成功")
        logger.info("Event pipeline completed successfully")
    except Exception as e:
        _ai_full_state['last_status'] = 'error'
        _add_schedule_log(f"事件管线异常: {str(e)[:100]}")
        logger.exception(f"Event pipeline error: {e}")
        # 异常时确保锁释放（正常路径由 _nightly 自行释放）
        task_lock.release('event')
    finally:
        _ai_full_state['running'] = False
        _ai_full_state['last_run'] = datetime.now().isoformat(timespec='seconds')


def _process_pending_cluster():
    """批处理 pending_cluster 文章：尝试匹配此后新产生的事件。
    在新文章处理完成后由定时任务触发（每天 1 次）。
    """
    from pipeline.event_matching import match_article_to_event
    from utils.db import get_db_connection

    db = get_db_connection(config.db_path)
    try:
        rows = db.execute("""
            SELECT id FROM news_articles
            WHERE content_status = 'pending_cluster'
            ORDER BY id DESC
        """).fetchall()
        total = len(rows)
        if total == 0:
            logger.info("pending_cluster 批处理: 无待处理文章")
            return

        logger.info(f"pending_cluster 批处理: {total} 篇待匹配")
        matched = 0
        for (aid,) in rows:
            try:
                event_id = match_article_to_event(aid)
                if event_id:
                    matched += 1
            except Exception as e:
                logger.warning(f"pending_cluster #{aid} 匹配失败: {e}")

        logger.info(f"pending_cluster 批处理完成: {matched}/{total} 篇成功匹配")
    finally:
        db.close()


async def _run_pending_cluster_job():
    """Wrapper for pending_cluster batch processing."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _process_pending_cluster)


async def trigger_ai_full_manual():
    """Manually trigger event pipeline (via API)."""
    global _ai_full_state
    _add_schedule_log("手动触发事件管线")
    import concurrent.futures
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_ai_full_job_sync)
    return {'status': 'ai_full_started'}
