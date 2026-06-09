"""
APScheduler-based pipeline scheduler.
Runs the news pipeline at 10:00 and 17:00 daily.
Can be toggled on/off via config.
"""
import os, sqlite3, logging, glob, time, asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from pipeline.run_all import run_pipeline

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

PIPELINE_CRON = [
    CronTrigger(hour=10, minute=0),   # 10:00
    CronTrigger(hour=17, minute=0),   # 17:00
]

# ── Pipeline status tracking ─────────────────────────────
_pipeline_state = {
    'running': False,
    'last_run': None,
    'last_status': None,
    'current_step': None,
    'steps': [],
}


def get_pipeline_status() -> dict:
    """Return current pipeline status (called by GET /api/pipeline/status)."""
    return dict(_pipeline_state)


async def _run_pipeline_job():
    """Wrapper that logs the pipeline run and updates status."""
    global _pipeline_state
    _pipeline_state.update(running=True, current_step='starting', steps=[])
    logger.info("Scheduled pipeline starting...")
    try:
        def progress_callback(status, message):
            _pipeline_state['current_step'] = message
            _pipeline_state['steps'].append({'name': message, 'status': status, 'duration_ms': 0})

        success = run_pipeline(
            db_path=config.db_path,
            user_agent=config.user_agent,
            callback=progress_callback,
        )
        _pipeline_state['last_status'] = 'success' if success else 'failed'
        if success:
            logger.info("Scheduled pipeline completed successfully")
        else:
            logger.error("Scheduled pipeline failed")
    except Exception as e:
        _pipeline_state['last_status'] = 'error'
        logger.exception(f"Scheduled pipeline error: {e}")
    finally:
        _pipeline_state['running'] = False
        _pipeline_state['last_run'] = datetime.now().isoformat(timespec='seconds')


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
        logger.info("Pipeline scheduler is disabled in config")
        return

    if not scheduler.running:
        for trigger in PIPELINE_CRON:
            scheduler.add_job(_run_pipeline_job, trigger)
        # Daily backup at 03:00
        scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0))
        scheduler.start()
        logger.info("Pipeline scheduler started: daily 10:00 / 17:00, backup at 03:00")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Pipeline scheduler stopped")


async def trigger_pipeline_manual():
    """Manually trigger a pipeline run (via API)."""
    asyncio.create_task(_run_pipeline_job())
    return {'status': 'pipeline_started'}
