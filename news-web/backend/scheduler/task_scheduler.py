"""统一任务队列调度器 — FIFO 队列 + worker 池。

同类型任务互斥（同一时刻只有一个同类型任务运行），
不同类型任务可并行（受 worker 池大小限制），
前端可动态调整并发数 (1-50)。
"""

import threading
import logging
from queue import Queue, Empty
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger(__name__)


@dataclass
class _Task:
    task_id: str
    task_type: str
    fn: Callable
    args: tuple
    kwargs: dict
    event: threading.Event = field(default_factory=threading.Event)
    cancelled: bool = False
    _running: bool = False
    result: Any = None
    error: Exception | None = None


class TaskScheduler:
    """统一 FIFO 任务队列 + worker 池。

    用法:
        sched = TaskScheduler(max_workers=10)
        task_id = sched.submit("article", process_article, aid)
        sched.set_workers(5)  # 动态调整并发数
        sched.shutdown()
    """

    MAX_WORKERS = 50
    MIN_WORKERS = 1

    def __init__(self, max_workers: int = 10):
        self._max_workers = max(1, min(max_workers, self.MAX_WORKERS))
        self._queue: Queue = Queue()
        self._tasks: dict[str, _Task] = {}
        self._lock = threading.Lock()
        self._active_types: set[str] = set()
        self._cv = threading.Condition(self._lock)
        self._running = True
        self._workers: list[threading.Thread] = []
        self._start_workers()

    def submit(self, task_type: str, fn: Callable, *args, **kwargs) -> str:
        """提交任务，返回 task_id。

        同类型任务互斥：如同类型任务正在运行，新任务排队等待。
        """
        import uuid
        task_id = f"{task_type}:{uuid.uuid4().hex[:8]}"
        task = _Task(
            task_id=task_id,
            task_type=task_type,
            fn=fn,
            args=args,
            kwargs=kwargs,
        )
        with self._lock:
            self._tasks[task_id] = task
        self._queue.put(task)
        logger.info(f"[TaskScheduler] 任务入队: {task_id}")
        return task_id

    def cancel(self, task_id: str) -> bool:
        """取消未开始的任务。已在执行的任务无法取消。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task._running:
                return False  # 正在执行，无法取消
            task.cancelled = True
            # 从 _tasks 字典中移除已取消的任务，防止内存泄漏
            del self._tasks[task_id]
            logger.info(f"[TaskScheduler] 取消任务: {task_id}")
        task.event.set()  # 通知 submitter 任务已被取消
        return True

    def set_workers(self, n: int):
        """动态调整 worker 数。"""
        n = max(self.MIN_WORKERS, min(n, self.MAX_WORKERS))
        old = self._max_workers
        self._max_workers = n
        if n > old:
            for _ in range(n - old):
                t = threading.Thread(target=self._worker_loop, daemon=True)
                t.start()
                self._workers.append(t)
        elif n < old:
            for _ in range(old - n):
                self._queue.put(None)
        logger.info(f"[TaskScheduler] Worker 数: {old} → {n}")

    @property
    def status(self) -> dict:
        """当前队列状态。"""
        with self._lock:
            pending = sum(1 for t in self._tasks.values() if not t._running and not t.cancelled)
            active = list(self._active_types)
            worker_count = sum(1 for w in self._workers if w.is_alive())
        return {
            "pending_tasks": pending,
            "active_types": active,
            "max_workers": self._max_workers,
            "worker_count": worker_count,
        }

    def shutdown(self):
        """停止所有 worker 线程。"""
        self._running = False
        # 放入哨兵唤醒所有 worker
        for _ in self._workers:
            self._queue.put(None)
        for t in self._workers:
            t.join(timeout=5)
        logger.info("[TaskScheduler] 已关闭")

    def _start_workers(self):
        for _ in range(self._max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self):
        """Worker 主循环 — 从队列取任务并执行。"""
        while self._running:
            try:
                task: _Task = self._queue.get(timeout=1)
            except Empty:
                continue

            if task is None:  # 哨兵
                break

            if task.cancelled:
                # 清理已取消任务的 _tasks 条目，防止内存泄漏
                with self._cv:
                    if task.task_id in self._tasks:
                        del self._tasks[task.task_id]
                task.event.set()
                continue

            # 原子操作：检查同类型互斥 + 预留类型 + 标记运行
            with self._cv:
                if task.task_type in self._active_types:
                    self._queue.put(task)
                    self._cv.wait(timeout=2)
                    if not self._running:
                        break
                    continue
                if task.cancelled:
                    continue
                self._active_types.add(task.task_type)
                task._running = True

            try:
                logger.info(f"[TaskScheduler] 开始执行: {task.task_id}")
                result = task.fn(*task.args, **task.kwargs)
                task.result = result
            except Exception as e:
                logger.error(f"[TaskScheduler] 任务失败: {task.task_id} — {e}")
                task.error = e
            finally:
                with self._cv:
                    self._active_types.discard(task.task_type)
                    if task.task_id in self._tasks:
                        del self._tasks[task.task_id]
                    self._cv.notify_all()
                task.event.set()


# 模块级单例
_scheduler: TaskScheduler | None = None


def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        raise RuntimeError("TaskScheduler 尚未初始化")
    return _scheduler


def init_scheduler(max_workers: int = 10) -> TaskScheduler:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
    _scheduler = TaskScheduler(max_workers=max_workers)
    logger.info(f"[TaskScheduler] Worker 数: {max_workers}")
    return _scheduler
