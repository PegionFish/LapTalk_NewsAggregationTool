"""调度器包 — 统一任务队列调度器 + APScheduler 定时调度。"""

from scheduler.task_scheduler import TaskScheduler, get_scheduler, init_scheduler

# 重新导出旧 APScheduler 调度器（从 scheduler_legacy.py 迁移）
from scheduler_legacy import (
    start_scheduler,
    stop_scheduler,
    trigger_pipeline_manual,
    trigger_ai_full_manual,
    get_pipeline_status,
    get_schedule_info,
    get_schedule_logs,
    reload_scheduler,
    scheduler as apscheduler,
    _pipeline_state,
    _ai_full_state,
)

__all__ = [
    # TaskScheduler
    "TaskScheduler",
    "get_scheduler",
    "init_scheduler",
    # Legacy APScheduler
    "start_scheduler",
    "stop_scheduler",
    "trigger_pipeline_manual",
    "trigger_ai_full_manual",
    "get_pipeline_status",
    "get_schedule_info",
    "get_schedule_logs",
    "reload_scheduler",
    "apscheduler",
    "_pipeline_state",
    "_ai_full_state",
]
