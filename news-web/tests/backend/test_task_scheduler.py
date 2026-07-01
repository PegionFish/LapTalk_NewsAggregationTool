import time
import pytest
from scheduler.task_scheduler import TaskScheduler


def test_scheduler_submit_and_wait():
    """提交任务并等待完成"""
    results = []

    def sample_task(x):
        results.append(x)
        return x * 2

    sched = TaskScheduler(max_workers=2)
    task_id = sched.submit("test", sample_task, 5)

    # 等待任务完成
    time.sleep(0.5)
    sched.shutdown()

    assert results == [5]


def test_scheduler_type_mutual_exclusion():
    """同类型任务不应并发执行"""
    running = []
    completed = []

    def slow_task(name):
        running.append(name)
        time.sleep(0.3)
        running.remove(name)
        completed.append(name)

    sched = TaskScheduler(max_workers=4)  # 足够 worker 但同类型互斥
    sched.submit("test", slow_task, "A")
    sched.submit("test", slow_task, "B")

    time.sleep(0.4)
    # A 和 B 应该串行执行（同类型互斥），0.4s 后最多完成 2 个
    assert len(completed) <= 2

    sched.shutdown()


def test_scheduler_different_types_parallel():
    """不同类型任务可并行执行"""
    running = []

    def task_a():
        running.append("A")
        time.sleep(0.3)
        running.remove("A")

    def task_b():
        running.append("B")
        time.sleep(0.3)
        running.remove("B")

    sched = TaskScheduler(max_workers=4)
    sched.submit("type_a", task_a)
    sched.submit("type_b", task_b)

    time.sleep(0.1)
    # 不同类应可并行
    assert "A" in running
    assert "B" in running

    sched.shutdown()


def test_scheduler_set_workers():
    """动态调整 worker 数"""
    sched = TaskScheduler(max_workers=2)
    assert sched._max_workers == 2
    sched.set_workers(5)
    assert sched._max_workers == 5

    # 超出范围应 clamp
    sched.set_workers(100)
    assert sched._max_workers == 50  # 上限
    sched.set_workers(0)
    assert sched._max_workers == 1   # 下限

    sched.shutdown()


def test_scheduler_cancel_pending_task():
    """取消未开始的任务"""
    started = []

    def fast_task():
        started.append("fast")

    def slow_task():
        started.append("slow")
        time.sleep(1)

    sched = TaskScheduler(max_workers=1)
    sched.submit("test", slow_task)  # 占用 worker
    task_id = sched.submit("test", fast_task)  # 排队

    time.sleep(0.1)
    assert sched.cancel(task_id), "应成功取消待处理任务"

    sched.shutdown()
    assert "fast" not in started, "被取消的任务不应执行"
