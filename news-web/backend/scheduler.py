"""
APScheduler-based pipeline scheduler.
Runs the news pipeline at configurable times daily (default 10:00 / 17:00).
Can be toggled on/off and schedule changed via config/API.
"""
import os, sqlite3, logging, glob, time, asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from pipeline.run_all import run_pipeline
from utils.task_lock import task_lock
from utils.task_state import task_state

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# ── Pipeline status tracking ─────────────────────────────
_pipeline_state = {
    'running': False,
    'last_run': None,
    'last_status': None,
    'current_step': None,
    'steps': [],
    'run_type': 'scheduled',
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
    """返回当前调度配置和状态。"""
    hours = config.pipeline_cron_hours
    minutes = config.pipeline_cron_minutes
    # 对齐长度：分钟数不够时补 0
    while len(minutes) < len(hours):
        minutes.append(0)
    schedule = []
    for i, h in enumerate(hours[:len(minutes)]):
        schedule.append({'hour': h, 'minute': minutes[i]})
    return {
        'enabled': config.pipeline_schedule_enabled,
        'schedule': schedule,
        'scheduler_running': scheduler.running,
        'last_run': _pipeline_state.get('last_run'),
        'last_status': _pipeline_state.get('last_status'),
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


def start_scheduler():
    """Start scheduler if enabled in config."""
    if not config.pipeline_schedule_enabled:
        _add_schedule_log("调度器已禁用（配置 pipeline_schedule_enabled=false）")
        logger.info("Pipeline scheduler is disabled in config")
        return

    if not scheduler.running:
        triggers = _build_cron_triggers()
        for trigger in triggers:
            scheduler.add_job(_run_pipeline_job, trigger)
        # Daily backup at 03:00
        scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0))
        scheduler.start()
        hours = config.pipeline_cron_hours
        minutes = config.pipeline_cron_minutes
        while len(minutes) < len(hours):
            minutes.append(0)
        time_strs = [f"{h:02d}:{minutes[i]:02d}" for i, h in enumerate(hours[:len(minutes)])]
        _add_schedule_log("调度器启动: 每天 " + ", ".join(time_strs) + " 运行")
        logger.info(f"Pipeline scheduler started: daily {', '.join(time_strs)}, backup at 03:00")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        _add_schedule_log("调度器已停止")
        logger.info("Pipeline scheduler stopped")


def reload_scheduler():
    """动态重载调度器 — 停止旧任务，根据新配置重新添加。"""
    global scheduler

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped for reload")

    # 重新创建 scheduler 实例（APScheduler shutdown 后需重新实例化）
    scheduler = AsyncIOScheduler()

    if not config.pipeline_schedule_enabled:
        _add_schedule_log("调度器重载: 已禁用")
        logger.info("Scheduler reload: disabled in config")
        return

    triggers = _build_cron_triggers()
    for trigger in triggers:
        scheduler.add_job(_run_pipeline_job, trigger)
    scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0))
    scheduler.start()

    hours = config.pipeline_cron_hours
    minutes = config.pipeline_cron_minutes
    while len(minutes) < len(hours):
        minutes.append(0)
    time_strs = [f"{h:02d}:{minutes[i]:02d}" for i, h in enumerate(hours[:len(minutes)])]
    _add_schedule_log("调度器重载: 每天 " + ", ".join(time_strs) + " 运行")
    logger.info(f"Scheduler reloaded: daily {', '.join(time_strs)}")


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
            task_state.update('pipeline', current=message, log_msg=f"{message}: {status}")
            _add_schedule_log(f"[pipeline] {message}: {status}")

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
