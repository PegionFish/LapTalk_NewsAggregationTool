"""
全局任务锁管理器 — AI 处理与数据采集独立调度，互不阻塞。

锁分组:
  AI 组 (level >= 1): 所有 AI 任务互斥 — 同一时刻只有一个 AI 任务运行
    ai_full, translate, analyze, keywords, classify, score,
    recluster, summarize_events, build_chains, rank_events, ai_filter
  数据组 (level == 0): 每类仅互斥自身 — 不同数据任务可共存，可与 AI 并行
    pipeline, cache_fetch, batch_retry, hotlist_fetch, update
"""
import threading, logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 任务类型 → 锁级别
# AI 组 (>=1): 互斥 — 同一时刻只有一个 AI 任务运行
# 数据组 (==0): 仅互斥同类型 — 数据采集与 AI 处理互不阻塞
TASK_LEVELS = {
    'ai_full':         2,  # 一键全量 AI（阻塞其他 AI，不阻塞数据采集）
    'translate':       1,
    'clean':           1,
    'analyze':         1,
    'keywords':        1,
    'classify':        1,
    'score':           1,
    'recluster':       1,
    'summarize_events': 1,
    'build_chains':    1,
    'rank_events':     1,
    'ai_filter':       1,
    'pipeline':        0,  # 数据采集管道（不阻塞 AI，仅互斥自身）
    'cache_fetch':     0,  # 抓取类：可与 AI 并行
    'batch_retry':     0,  # 抓取类：可与 AI 并行
    'hotlist_fetch':   0,  # 抓取类：可与 AI 并行
    'update':          0,  # 系统更新：独立操作
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
                # AI 组 (level >= 1) 互斥所有 AI 任务
                if level >= 1 and active_level >= 1:
                    return False, f"AI task '{active_type}' is running since {info['started_at']}"
                # 数据组 (level == 0) 仅互斥同类型任务
                if level == 0 and active_level == 0 and task_type == active_type:
                    return False, f"Data task '{task_type}' is already running since {info['started_at']}"
                # AI ↔ 数据：互不阻塞，放行

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
                # AI 组互斥
                if level >= 1 and active_level >= 1:
                    return True
                # 数据组仅互斥同类型
                if level == 0 and active_level == 0 and task_type == active_type:
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
