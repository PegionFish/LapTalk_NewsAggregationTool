"""
全局任务锁管理器 — 确保同一时间只能运行一个 AI/管道任务。

锁级别:
  full_level=2 (互斥一切): pipeline, ai_full
  full_level=1 (互斥 AI 任务): translate, analyze, keywords, classify, score,
                                recluster, summarize_events, build_chains, rank_events, ai_filter
  full_level=0 (仅互斥同类): cache_fetch, batch_retry, hotlist_fetch, update
"""
import threading, logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 任务类型 → 锁级别
TASK_LEVELS = {
    'pipeline':        2,  # 全流程
    'ai_full':         2,  # 一键全量 AI
    'translate':       1,
    'analyze':         1,
    'keywords':        1,
    'classify':        1,
    'score':           1,
    'recluster':       1,
    'summarize_events': 1,
    'build_chains':    1,
    'rank_events':     1,
    'ai_filter':       1,
    'cache_fetch':     0,
    'batch_retry':     0,
    'hotlist_fetch':   0,
    'update':          0,
}


class TaskLockManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._active: dict = {}  # task_type → {started_at, task_id}
        self._waiting: list[str] = []

    def acquire(self, task_type: str, task_id: str = '') -> tuple[bool, str]:
        """
        尝试获取任务锁。
        返回 (acquired, reason)。
        """
        if task_type not in TASK_LEVELS:
            return False, f"Unknown task type: {task_type}"

        level = TASK_LEVELS[task_type]
        now = datetime.now().isoformat(timespec='seconds')

        with self._lock:
            # 检查是否有冲突的活跃任务
            for active_type, info in self._active.items():
                active_level = TASK_LEVELS.get(active_type, 0)
                # level 2 互斥一切
                if level == 2 or active_level == 2:
                    return False, f"Task '{active_type}' is running since {info['started_at']}"
                # level 1 互斥其他 level 1+
                if level >= 1 and active_level >= 1:
                    return False, f"Task '{active_type}' is running since {info['started_at']}"
                # level 0 互斥同类型
                if level == 0 and active_level == 0 and task_type == active_type:
                    return False, f"Task '{task_type}' is already running"

            # 获取锁
            self._active[task_type] = {
                'started_at': now,
                'task_id': task_id or f"{task_type}:{now}",
            }
            logger.info(f"[TaskLock] Acquired: {task_type} ({task_id or now})")
            return True, ''

    def release(self, task_type: str):
        """释放任务锁。"""
        with self._lock:
            if task_type in self._active:
                info = self._active.pop(task_type)
                logger.info(f"[TaskLock] Released: {task_type} ({info.get('task_id', '')})")

    def is_busy(self, task_type: str = '') -> bool:
        """检查是否有任务在运行。如指定 type，检查该类型或更高级别。"""
        with self._lock:
            if not task_type:
                return len(self._active) > 0
            level = TASK_LEVELS.get(task_type, 0)
            for active_type in self._active:
                active_level = TASK_LEVELS.get(active_type, 0)
                if level >= 1 and active_level >= 1:
                    return True
                if level == 0 and task_type == active_type:
                    return True
                if level == 2 or active_level == 2:
                    return True
            return False

    def get_active(self) -> dict:
        """返回当前活跃任务信息。"""
        with self._lock:
            return dict(self._active)

    def get_running_tasks(self) -> list[str]:
        """返回当前所有运行中的任务类型列表。"""
        with self._lock:
            return list(self._active.keys())


# 全局单例
task_lock = TaskLockManager()
