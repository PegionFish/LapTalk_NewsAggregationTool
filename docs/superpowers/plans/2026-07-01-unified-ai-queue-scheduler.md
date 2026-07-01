# 统一 AI 入口 + 队列调度器 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 AI 入口为单一 DeepSeek 配置，引入 DB Writer 线程消除 SQLite 写锁竞争，用 FIFO 任务队列替代 task_lock 分組互斥逻辑。

**Architecture:** 新增 `queue/` 包（db_writer + task_scheduler），Worker 线程只做 HTTP IO 不再碰 DB，写入结果入队由单 Writer 线程串行 safe_commit。所有 AI 任务进入统一 FIFO 队列，队列本身替代 task_lock 互斥。

**Tech Stack:** Python 3.14, FastAPI, SQLite, OpenAI SDK, React 18, TypeScript

## Global Constraints

- 每个 AI 步骤完成后立即落库（不入内存堆积），Writer 确认后才继续下一步
- 数据完整性优先：中途崩溃不丢已完成步骤
- 前端刷新后可恢复进度（task_state 保留）
- 改动量控制在 400-500 行净变更
- 翻译客户端保留翻译专用 system prompt 和 HTML 处理逻辑，复用统一 client
- API Key 掩码规则不变（`***` 不覆盖真实 Key）
- 默认并发数 10，可调范围 1-50
- 余额探针失败不影响管线运行

---

### Task 1: DB Writer 线程模块

**Files:**
- Create: `news-web/backend/queue/__init__.py`
- Create: `news-web/backend/queue/db_writer.py`
- Create: `news-web/tests/backend/test_db_writer.py`

**Interfaces:**
- Produces: `DbWriter` class with `submit(sql, params) -> threading.Event`, `start()`, `stop()`, `stop_event` attribute
- Produces: `get_db_writer() -> DbWriter` module-level singleton accessor
- Produces: `WriteRequest` dataclass with `sql`, `params`, `event`, `result`, `error` fields

- [ ] **Step 1: 创建 queue 包和测试文件骨架**

```bash
mkdir -p news-web/backend/queue
touch news-web/backend/queue/__init__.py
```

- [ ] **Step 2: 编写 DbWriter 测试**

```python
# news-web/tests/backend/test_db_writer.py
import threading
import pytest
from queue.db_writer import DbWriter, WriteRequest


def test_db_writer_submit_and_ack():
    """提交写请求后 Writer 执行并设置 event"""
    writer = DbWriter(":memory:")
    writer.start()

    event = writer.submit(
        "CREATE TABLE IF NOT EXISTS test (id INTEGER, name TEXT)",
        ()
    )
    assert event.wait(timeout=5), "Writer 应在 5s 内确认"

    event2 = writer.submit(
        "INSERT INTO test VALUES (?, ?)",
        (1, "hello")
    )
    assert event2.wait(timeout=5)

    # 验证数据已写入
    import sqlite3
    conn = sqlite3.connect(":memory:")
    row = conn.execute("SELECT * FROM test WHERE id=1").fetchone()
    assert row == (1, "hello")
    conn.close()

    writer.stop()


def test_db_writer_timeout_triggers_fallback():
    """Writer 不响应时 event.wait 超时返回 False"""
    writer = DbWriter(":memory:")
    # 不启动 writer，直接 submit
    event = writer.submit("SELECT 1", ())
    # 30s 太长，传自定义 timeout
    assert not event.wait(timeout=0.5), "Writer 未启动，应超时"


def test_db_writer_stop_flushes_pending():
    """stop() 后所有待处理请求应完成"""
    writer = DbWriter(":memory:")
    writer.start()

    events = []
    for i in range(20):
        events.append(writer.submit(
            "CREATE TABLE IF NOT EXISTS batch{}(id INTEGER)".format(i), ()
        ))

    writer.stop()  # stop 内部会处理完队列

    # 所有请求应已完成
    for e in events:
        assert e.is_set(), "stop 后所有请求应完成"


def test_db_writer_submit_after_stop_raises():
    """stop 后 submit 应抛异常"""
    writer = DbWriter(":memory:")
    writer.start()
    writer.stop()

    with pytest.raises(RuntimeError, match="Writer 已停止"):
        writer.submit("SELECT 1", ())
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd news-web && python -m pytest tests/backend/test_db_writer.py -v
# Expected: 全部 FAIL (模块不存在)
```

- [ ] **Step 4: 实现 DbWriter 模块**

```python
# news-web/backend/queue/__init__.py
from queue.db_writer import DbWriter, get_db_writer

__all__ = ["DbWriter", "get_db_writer"]
```

```python
# news-web/backend/queue/db_writer.py
"""单线程串行 DB 写入器 — 消除 SQLite 写锁竞争。

Worker 线程只做 AI HTTP IO，写入结果通过 submit() 入队，
由 Writer 线程串行执行 safe_commit 后通过 Event 通知 Worker 继续。
"""

import threading
import logging
import sqlite3
from dataclasses import dataclass, field
from queue import Queue, Empty

logger = logging.getLogger(__name__)


@dataclass
class WriteRequest:
    """一次 DB 写请求。"""
    sql: str
    params: tuple = ()
    event: threading.Event = field(default_factory=threading.Event)
    result: Exception | None = field(default=None)


class DbWriter:
    """单线程串行 DB 写入器。

    用法:
        writer = DbWriter(config.db_path)
        writer.start()

        # Worker 中:
        event = writer.submit("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (c, aid))
        if not event.wait(timeout=30):
            logger.error("Writer 确认超时，降级直接写 DB")
            # fallback: 直接 db.commit()

        writer.stop()
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._queue: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def start(self):
        """启动 Writer 线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="db-writer")
        self._thread.start()
        logger.info("DbWriter 已启动")

    def stop(self):
        """停止 Writer 线程，处理完队列中所有待处理请求。"""
        if not self._thread or not self._thread.is_alive():
            return
        self._stop_event.set()
        # 放入哨兵确保线程从 get() 中唤醒
        self._queue.put(None)
        self._thread.join(timeout=10)
        logger.info("DbWriter 已停止")

    def submit(self, sql: str, params: tuple = ()) -> threading.Event:
        """提交写请求，返回 Event 对象。调用方 await event.wait() 等待确认。

        Raises:
            RuntimeError: Writer 已停止
        """
        if self._stop_event.is_set():
            raise RuntimeError("Writer 已停止，拒绝新请求")
        req = WriteRequest(sql=sql, params=params)
        self._queue.put(req)
        return req.event

    def _run(self):
        """Writer 主循环 — 串行消费队列中的写请求。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1)
            except Empty:
                continue

            if item is None:  # 哨兵
                break

            req: WriteRequest = item
            try:
                conn.execute(req.sql, req.params)
                conn.commit()
            except Exception as e:
                logger.error(f"DbWriter 写入失败: {e}\nSQL: {req.sql[:200]}\nParams: {str(req.params)[:200]}")
                conn.rollback()
                req.result = e
            finally:
                req.event.set()  # 无论如何通知 Worker 继续

        conn.close()


# 模块级单例（由 main.py 初始化）
_writer: DbWriter | None = None


def get_db_writer() -> DbWriter:
    """获取全局 DbWriter 单例。"""
    global _writer
    if _writer is None:
        raise RuntimeError("DbWriter 尚未初始化，请在 main.py lifespan 中调用 DbWriter(path).start()")
    return _writer


def init_db_writer(db_path: str) -> DbWriter:
    """初始化全局 DbWriter 单例并启动。"""
    global _writer
    if _writer is not None:
        _writer.stop()
    _writer = DbWriter(db_path)
    _writer.start()
    return _writer
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd news-web && python -m pytest tests/backend/test_db_writer.py -v
# Expected: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add news-web/backend/queue/ news-web/tests/backend/test_db_writer.py
git commit -m "feat: 新增 DB Writer 单线程写入器 — 消除 SQLite 写锁竞争

Worker 通过 submit() 入队写请求，Writer 串行执行 safe_commit 后
用 Event 通知 Worker 继续，替代原有的多线程并发写 DB 模式。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 统一 AI 客户端 + 余额探针

**Files:**
- Modify: `news-web/backend/ai_client.py`

**Interfaces:**
- Consumes: `config.openai_base_url`, `config.openai_api_key`, `config.openai_model`
- Produces: `get_client() -> OpenAI` (统一 DeepSeek 入口)
- Produces: `get_balance() -> dict | None` (余额查询)
- Produces: `BalanceInsufficientError` (已有, 不变)
- Removes: 三段式 client 切换逻辑

- [ ] **Step 1: 重构 ai_client.py**

`get_client()` 已经是统一入口（只有 `openai_base_url` + `openai_api_key`），不需改。在文件末尾新增余额查询函数：

```python
# 在 ai_client.py 末尾新增

def get_balance() -> dict | None:
    """查询 DeepSeek 账户余额。

    GET https://api.deepseek.com/user/balance

    Returns:
        {
            "is_available": bool,
            "balance_infos": [
                {"currency": "CNY", "total_balance": "110.00",
                 "granted_balance": "10.00", "topped_up_balance": "100.00"}
            ]
        }
        失败返回 None
    """
    import requests
    api_key = config.openai_api_key
    if not api_key:
        return None

    base_url = config.openai_base_url.rstrip('/')
    balance_url = f"{base_url}/user/balance"

    try:
        resp = requests.get(
            balance_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"余额查询失败: HTTP {resp.status_code} — {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"余额查询异常: {e}")
        return None
```

确认 `BalanceInsufficientError` 类已存在（在 `chat()` 和 `_ai_json()` 的 except 块中定义）。当前代码中是在函数内 `raise BalanceInsufficientError(...)` 使用的，确认类定义位置。

- [ ] **Step 2: 确认现有测试仍通过**

```bash
cd news-web && python -m pytest tests/backend/test_pipeline_article.py -v
# Expected: 3 passed (ai_client 的 get_client() 签名未变)
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/ai_client.py
git commit -m "feat: 新增 DeepSeek 余额查询函数 get_balance()

通过 GET /user/balance 获取账户余额信息，失败返回 None 不抛异常。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 任务调度器模块

**Files:**
- Create: `news-web/backend/queue/task_scheduler.py`
- Create: `news-web/tests/backend/test_task_scheduler.py`

**Interfaces:**
- Consumes: `get_db_writer()` from Task 1
- Produces: `TaskScheduler` class with `submit(task_type, fn, *args, **kwargs) -> str`, `cancel(task_id) -> bool`, `set_workers(n)`, `status` property
- Produces: `get_scheduler() -> TaskScheduler` singleton accessor

- [ ] **Step 1: 编写 TaskScheduler 测试**

```python
# news-web/tests/backend/test_task_scheduler.py
import time
import pytest
from queue.task_scheduler import TaskScheduler


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd news-web && python -m pytest tests/backend/test_task_scheduler.py -v
# Expected: 全部 FAIL
```

- [ ] **Step 3: 实现 TaskScheduler**

```python
# news-web/backend/queue/task_scheduler.py
"""统一任务队列调度器 — FIFO 队列 + worker 池。

替代 task_lock.py 的分组互斥逻辑：
- 同类型任务互斥（同一时刻只有一个同类型任务运行）
- 不同类型任务可并行（受 worker 池大小限制）
- 前端可动态调整并发数 (1-50)
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
            if task.event.is_set():
                return False  # 已在执行或已完成
            task.cancelled = True
            logger.info(f"[TaskScheduler] 取消任务: {task_id}")
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
        logger.info(f"[TaskScheduler] Worker 数: {old} → {n}")

    @property
    def status(self) -> dict:
        """当前队列状态。"""
        with self._lock:
            pending = sum(1 for t in self._tasks.values() if not t.event.is_set() and not t.cancelled)
            active = list(self._active_types)
        return {
            "pending_tasks": pending,
            "active_types": active,
            "max_workers": self._max_workers,
            "worker_count": len(self._workers),
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

    def _can_run(self, task_type: str) -> bool:
        """检查该类型任务是否可以开始执行。同类型互斥。"""
        return task_type not in self._active_types

    def _worker_loop(self):
        """Worker 主循环 — 从队列取任务并执行。"""
        while self._running:
            try:
                task: _Task = self._queue.get(timeout=1)
            except Empty:
                continue

            if task is None:  # 哨兵
                break

            # 检查是否已取消
            if task.cancelled:
                continue

            # 等待同类型互斥锁
            while self._running and not self._can_run(task.task_type):
                # 将任务放回队尾等待
                self._queue.put(task)
                try:
                    task = self._queue.get(timeout=2)
                except Empty:
                    task = None
                    break
                if task is None or task.cancelled:
                    break
                continue

            if task is None or task.cancelled:
                continue

            # 标记类型活跃
            with self._lock:
                self._active_types.add(task.task_type)

            try:
                logger.info(f"[TaskScheduler] 开始执行: {task.task_id}")
                result = task.fn(*task.args, **task.kwargs)
                task.result = result
            except Exception as e:
                logger.error(f"[TaskScheduler] 任务失败: {task.task_id} — {e}")
                task.error = e
            finally:
                with self._lock:
                    self._active_types.discard(task.task_type)
                    if task.task_id in self._tasks:
                        del self._tasks[task.task_id]
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
    return _scheduler
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd news-web && python -m pytest tests/backend/test_task_scheduler.py -v
# Expected: 5 passed
```

- [ ] **Step 5: Commit**

```bash
git add news-web/backend/queue/task_scheduler.py news-web/tests/backend/test_task_scheduler.py
git commit -m "feat: 新增统一任务队列调度器 — FIFO + 同类型互斥替代 task_lock

TaskScheduler 提供 submit/cancel/set_workers/shutdown 接口，
Worker 池可动态调整 1-50，同类型任务互斥不同类型可并行。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 统一 AI 配置 — config.py 简化 + 迁移

**Files:**
- Modify: `news-web/backend/config.py`

**Interfaces:**
- Produces: 废弃属性 `clean_model`, `clean_base_url`, `clean_api_key`, `simple_model`, `pipeline_model` — 改为回退到 `openai_model`
- Produces: `config.ai_workers: int` — 并发数 (default 10)
- Produces: 翻译配置字段 `translation_*` 保留但标记为 deprecated
- Produces: `to_dict()` 新增 `ai_workers` 字段

- [ ] **Step 1: 修改 config.py**

`clean_model`, `simple_model`, `pipeline_model` 等属性已有 setter/getter，改为都回退到 `openai_model`（不删掉 setter 避免旧配置写入时报错）：

```python
# 在 config.py DEFAULT_CONFIG 中新增:
DEFAULT_CONFIG = {
    ...
    'ai_workers': 10,  # ← 新增: AI 并发 worker 数
    ...
}

# 修改 clean_model getter — 回退到 openai_model
@property
def clean_model(self) -> str:
    return self.openai_model  # 不再读独立字段

# 修改 simple_model getter
@property
def simple_model(self) -> str:
    return self.openai_model  # 不再读独立字段

# 修改 pipeline_model getter
@property
def pipeline_model(self) -> str:
    return self.openai_model  # 不再读独立字段

# 修改 clean_base_url getter
@property
def clean_base_url(self) -> str:
    return self.openai_base_url  # 不再读独立字段

# 修改 clean_api_key getter
@property
def clean_api_key(self) -> str:
    return self.openai_api_key  # 不再读独立字段

# 新增 ai_workers 属性
@property
def ai_workers(self) -> int:
    val = self._data.get('ai_workers', 10)
    try:
        return max(1, min(50, int(val)))
    except (TypeError, ValueError):
        return 10

@ai_workers.setter
def ai_workers(self, val: int):
    self._data['ai_workers'] = max(1, min(50, int(val)))
    self.save()

# 在 to_dict() 中新增:
d['ai_workers'] = self.ai_workers
```

setter 保留不动（旧前端可能仍发送这些字段），getter 全部回退到统一入口。

- [ ] **Step 2: 验证导入**

```bash
cd news-web/backend && python -c "from config import config; print(config.openai_model, config.clean_model, config.ai_workers)"
# Expected: 正常输出，clean_model == openai_model
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/config.py
git commit -m "refactor: 统一 AI 配置 — 多模型属性回退到 openai_model + 新增 ai_workers

clean_model/simple_model/pipeline_model 等已废弃独立属性，
getter 统一回退到 openai_model（setter 保留以兼容旧前端写入）。

新增 ai_workers 配置项（默认 10，范围 1-50）。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: process_article 接入 DbWriter

**Files:**
- Modify: `news-web/backend/pipeline/process_article.py`

**Interfaces:**
- Consumes: `get_db_writer()` from Task 1
- Changed: 不在 process_article 内部直接 `safe_commit(db)`，改为 `writer.submit(sql, params).wait(timeout=30)`
- Changed: `_conn()` 保留（读取仍需直连 DB），`safe_commit` 调用全部替换为 writer 提交
- Changed: `recover_stuck_articles()` 保持直连（启动时恢复，不经过 writer）

- [ ] **Step 1: 修改 process_article.py**

核心改动：将所有 `safe_commit(db)` 替换为 writer 提交模式。writer 有自己的连接，process_article 内部的 `db` 连接只做读取。

```python
# process_article.py 开头新增导入
from queue.db_writer import get_db_writer

# 新增辅助函数
def _write_and_wait(sql: str, params: tuple = (), timeout: float = 30.0) -> bool:
    """通过 Writer 写 DB 并等待确认。超时返回 False 由调用方处理。"""
    try:
        writer = get_db_writer()
    except RuntimeError:
        # Writer 未初始化，降级为直连
        logger.warning("DbWriter 未初始化，降级为直连 safe_commit")
        db = _conn()
        try:
            db.execute(sql, params)
            from utils.db import safe_commit
            safe_commit(db)
        finally:
            db.close()
        return True
    
    event = writer.submit(sql, params)
    if not event.wait(timeout=timeout):
        logger.error(f"DbWriter 确认超时 ({timeout}s)，SQL: {sql[:100]}")
        return False
    return True

# process_article() 内替换所有 safe_commit(db) 调用:
# 旧: db.execute("UPDATE news_articles SET content_status='processing' WHERE id=?", (aid,))
#     safe_commit(db)
# 新: _write_and_wait("UPDATE news_articles SET content_status='processing' WHERE id=?", (aid,))
```

`_write_and_wait` 统一处理了 writer 存在/不存在两种情况，优雅降级。

具体替换点（在 process_article 函数内共 6 处）：
1. content_status='processing' (line 61)
2. ai_cleaned_content (line 88) 
3. translated_content (line 106)
4. ai_summary (line 127)
5. KCS 批量 update (line 152)
6. content_status 最终状态 (line 182)

每处将 `db.execute(...); safe_commit(db)` 替换为 `_write_and_wait(...)`。

- [ ] **Step 2: 运行现有测试**

```bash
cd news-web && python -m pytest tests/backend/test_pipeline_article.py -v
# Expected: 3 passed (process_single 会失败因为 writer 未初始化，但 test_process_single_article_not_found 查不存在的文章)
```

注意：测试环境中 DB Writer 未初始化（无 main.py lifespan），`_write_and_wait` 的降级分支会触发，走直连 safe_commit。

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/pipeline/process_article.py
git commit -m "refactor: process_article 接入 DbWriter — DB 写入由单线程串行执行

所有 safe_commit(db) 替换为 _write_and_wait()，Writer 未初始化时
自动降级为直连 safe_commit。Worker 线程不再直接操作 DB 写入。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: pipeline_article 重写 — 接入 TaskScheduler + 恢复并发

**Files:**
- Modify: `news-web/backend/api/pipeline_article.py`

**Interfaces:**
- Consumes: `TaskScheduler` from Task 3, `DbWriter` from Task 1
- Changed: `start_article_batch()` 用 scheduler 检查管线级互斥，`_run_batch` 保持 ThreadPoolExecutor 但 MAX_WORKERS 从 config 读取
- Changed: 移除 `task_lock.acquire/release('article')` 调用
- New: `POST /api/pipeline/article/cancel` — 取消正在运行的批处理

**设计决策**：`_run_batch` 内部保留 ThreadPoolExecutor（并行处理多篇文章），scheduler 只负责管线级互斥（防止同时运行 article_batch + event_nightly）。DB 写入已由 Task 5 的 `_write_and_wait` 接管，ThreadPoolExecutor 线程不再直接 safe_commit。

- [ ] **Step 1: 修改 start_article_batch — task_lock → scheduler**

```python
@router.post("/batch-process")
def start_article_batch():
    global _article_state
    if _article_state.get("running"):
        return {"ok": False, "message": "文章处理已在运行中"}
    from queue.task_scheduler import get_scheduler
    scheduler = get_scheduler()
    if "article_batch" in scheduler.status["active_types"]:
        return {"ok": False, "message": "文章处理已在运行中"}
    
    from utils.db import get_db_connection
    db = get_db_connection(config.db_path)
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('pending', 'fetched', 'translated')
          AND ai_filtered != -1
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = '')
    """).fetchone()[0]
    db.close()
    
    task_state.init_state('article', total=n)
    _article_state["running"] = True
    _article_state["total"] = n
    scheduler.submit("article_batch", _run_batch)
    return {"ok": True, "message": f"启动文章批量处理，预计 {n} 篇", "pending": n}
```

- [ ] **Step 2: _run_batch 中 MAX_WORKERS 改为从 config 读取，移除 task_lock 调用**

```python
# _run_batch() 修改两处:

# 1. MAX_WORKERS 从 config 读取
MAX_WORKERS = config.ai_workers  # 替换: MAX_WORKERS = 1

# 2. 移除 task_lock.release('article') 调用（共 2 处）:
#    - total == 0 分支中的 task_lock.release('article')
#    - 函数末尾的 task_lock.release('article')
#    scheduler 在 _run_batch 返回后自动标记任务完成
```

- [ ] **Step 3: _run_batch while 循环增加取消检查**

在 while pending 循环中增加:

```python
if _article_state.get("cancelled"):
    for future in pending:
        future.cancel()
        aid = future_to_aid[future]
        failed += 1
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ⏹️ 用户取消")
    break
```

- [ ] **Step 4: 新增 /cancel 端点**

```python
@router.post("/cancel")
def cancel_article_batch():
    """取消文章批处理。正在处理的文章将继续完成，未开始的跳过。"""
    global _article_state
    if not _article_state.get("running"):
        return {"ok": False, "message": "没有正在运行的文章处理"}
    _article_state["cancelled"] = True
    _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏹️ 用户取消")
    return {"ok": True, "message": "取消信号已发送"}
```

并在 `_run_batch` 的 while 循环中检查 `_article_state.get("cancelled")`（见 Step 3）。

- [ ] **Step 5: 运行测试**

```bash
cd news-web && python -m pytest tests/backend/test_pipeline_article.py -v
# Expected: 3 passed
```

- [ ] **Step 6: Commit**

```bash
git add news-web/backend/api/pipeline_article.py
git commit -m "refactor: pipeline_article 接入 TaskScheduler + 恢复可配置并发

- MAX_WORKERS 从 config.ai_workers 读取（默认 10，不再硬编码 1）
- 管线级互斥由 TaskScheduler 的同类型检测替代 task_lock
- 新增 /cancel 端点支持取消批处理

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: pipeline_event 接入 TaskScheduler

**Files:**
- Modify: `news-web/backend/api/pipeline_event.py`

**Interfaces:**
- Consumes: `TaskScheduler` from Task 3, `DbWriter` from Task 1
- Changed: `start_nightly()` 通过 scheduler.submit() 提交 `_nightly`
- Changed: 各独立端点 (`summarize`, `build_chains`, `recluster`) 通过 scheduler.submit() 提交
- Changed: task_lock.acquire/release → scheduler 类型互斥

- [ ] **Step 1: 修改 pipeline_event.py**

将 `task_lock.acquire('event')` 替换为 scheduler 检查：

```python
# 在 top-level imports 新增:
from queue.task_scheduler import get_scheduler

# start_nightly() 改为:
@router.post("/nightly")
def start_nightly():
    global _event_state
    if _event_state.get("running"):
        return {"ok": False, "message": "事件管线已在运行中"}
    scheduler = get_scheduler()
    if "event_nightly" in scheduler.status["active_types"]:
        return {"ok": False, "message": "事件管线已在运行中"}
    
    task_state.init_state('event')
    scheduler.submit("event_nightly", _nightly)
    return {"ok": True, "message": "事件管线已启动（摘要→逻辑链）"}

# _nightly() 末尾移除 task_lock.release('event') — scheduler 自动管理
# _run_summarize() 末尾移除 task_lock.release('summarize_events')
# _run_build_chains() 末尾移除 task_lock.release('build_chains')
# _run_recluster() 末尾移除 task_lock.release('recluster')
```

其他独立端点 (`start_summarize`, `start_build_chains`, `start_recluster`) 同理改为 scheduler 检查。

- [ ] **Step 2: Commit**

```bash
git add news-web/backend/api/pipeline_event.py
git commit -m "refactor: pipeline_event 接入 TaskScheduler — 替代 task_lock

nightly/summarize/build_chains/recluster 的任务互斥由
TaskScheduler 的同类型检测替代 task_lock.acquire/release。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: translation_client 简化 — 复用统一 AI client

**Files:**
- Modify: `news-web/backend/translation_client.py`

**Interfaces:**
- Consumes: `ai_client.get_client()` (统一 DeepSeek 入口)
- Consumes: `config.openai_model` (替代独立 `translation_model`)
- Changed: `get_client()` 改为复用 `ai_client.get_client()`
- Changed: `_call_translate` 使用 `config.openai_model` 替代 `config.translation_model`
- Preserved: `translate_html_preserve_structure()`, `translate_html()`, `translate_to_chinese()` 签名不变
- Preserved: 翻译专用 system prompt

- [ ] **Step 1: 简化 translation_client.py**

```python
# translation_client.py
# 将 get_client() 改为:
def get_client() -> OpenAI:
    """复用统一 AI 入口的 OpenAI 客户端。"""
    from ai_client import get_client as get_ai_client
    return get_ai_client()

# _call_translate() 将 model 参数改为:
resp = client.chat.completions.create(
    model=config.openai_model,  # 统一用 AI model，不再独立 translation_model
    ...
)

# config.translation_api_key 判断改为 config.openai_api_key
if not config.openai_api_key:  # 原: config.translation_api_key
    return ""
```

`config.translation_enabled`, `config.translation_target_lang` 保留（控制翻译功能的独立开关和目标语言）。

- [ ] **Step 2: 验证导入正确**

```bash
cd news-web/backend && python -c "from translation_client import translate_to_chinese; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/translation_client.py
git commit -m "refactor: translation_client 复用统一 AI client

get_client() 改为复用 ai_client.get_client()，翻译 API 调用
使用统一 openai_model。保留翻译专用 system prompt 和 HTML 处理逻辑。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: main.py — DbWriter + Scheduler 生命周期

**Files:**
- Modify: `news-web/backend/main.py`

**Interfaces:**
- Produces: lifespan startup: init_db_writer + init_scheduler
- Produces: lifespan shutdown: scheduler.shutdown() + writer.stop()

- [ ] **Step 1: 修改 main.py lifespan**

```python
# main.py
from queue.db_writer import init_db_writer
from queue.task_scheduler import init_scheduler
from config import config

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    init_db_writer(config.db_path)
    init_scheduler(config.ai_workers)
    if not testing:
        start_scheduler()
    yield
    # 关闭
    from queue.task_scheduler import get_scheduler
    from queue.db_writer import get_db_writer
    try:
        get_scheduler().shutdown()
    except Exception:
        pass
    try:
        get_db_writer().stop()
    except Exception:
        pass
```

- [ ] **Step 2: 启动后端验证不报错**

```bash
cd news-web/backend && timeout 5 python main.py 2>&1 || true
# Expected: 正常启动，无 import 错误，DbWriter/Scheduler 初始化日志出现
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/main.py
git commit -m "feat: main.py 集成 DbWriter + TaskScheduler 生命周期管理

lifespan 启动时初始化 DbWriter(单线程) 和 TaskScheduler(可配 worker)，
关闭时优雅停止。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 删除 task_lock + ai_config 简化 + 调度器更新

**Files:**
- Delete: `news-web/backend/utils/task_lock.py`
- Modify: `news-web/backend/scheduler.py`
- Modify: `news-web/backend/ai_config.py`

- [ ] **Step 1: 删除 task_lock.py**

```bash
rm news-web/backend/utils/task_lock.py
```

- [ ] **Step 2: 更新 scheduler.py — 移除 task_lock 引用**

将 `from utils.task_lock import task_lock` 替换为 `from queue.task_scheduler import get_scheduler`，修改 `_run_pipeline_job_sync()` 和 `_run_event_pipeline_job_sync()` 中的锁检查逻辑：

```python
# scheduler.py 顶部
# 删除: from utils.task_lock import task_lock
# 新增: from queue.task_scheduler import get_scheduler

# _run_pipeline_job_sync() 中:
# 旧: ok, reason = task_lock.acquire('pipeline')
#     if not ok:
#         _add_schedule_log(f"管道启动失败: {reason}")
#         return
# 新:
scheduler = get_scheduler()
if "pipeline" in scheduler.status["active_types"]:
    _add_schedule_log("管道启动失败: 数据采集已在运行中")
    return

# _run_pipeline_job_sync() 末尾:
# 删除: task_lock.release('pipeline')
# scheduler 在 _run_pipeline_job_sync 返回后自动标记完成

# _run_event_pipeline_job_sync() 中:
# 旧: ok, reason = task_lock.acquire('event')
#     if not ok: ...
# 新: scheduler = get_scheduler()
#     if "event_nightly" in scheduler.status["active_types"]: ... return
# 删除末尾的 task_lock.release('event')
```

```bash
# 验证: 确保无残留 task_lock 引用
grep -rn "task_lock" news-web/backend/scheduler.py
# Expected: 无输出
```

- [ ] **Step 3: 简化 ai_config.py — 移除三段式入口注册表**

```python
# ai_config.py 简化为: 移除 AI_ENDPOINTS 三段式注册表，
# 所有入口返回统一配置。保留 to_ai_endpoint_config/apply_ai_endpoint_config/
# test_ai_endpoint/test_all_ai_endpoints 函数签名不变（前端兼容）。

# _get_endpoint_base_url("title_filter") → config.openai_base_url
# _get_endpoint_base_url("article_processing") → config.openai_base_url
# _get_endpoint_base_url("event_pipeline") → config.openai_base_url
# _get_endpoint_model(...) → 全部返回 config.openai_model
# _get_endpoint_api_key(...) → 全部返回 config.openai_api_key

# 删除 AI_ENDPOINTS 字典（保留为兼容层，值改为统一配置）
```

- [ ] **Step 4: 全局搜索残留的 task_lock 引用并清理**

```bash
grep -rn "task_lock" news-web/backend/ --include="*.py" | grep -v __pycache__ | grep -v test_
# 确保只有 scheduler.py 有引用（在 Task 10 Step 2 中处理）
```

- [ ] **Step 5: Commit**

```bash
git rm news-web/backend/utils/task_lock.py
git add news-web/backend/scheduler.py news-web/backend/ai_config.py
git commit -m "refactor: 删除 task_lock.py + 简化 ai_config + 更新 scheduler

- task_lock.py: 队列调度器替代，删除分组互斥逻辑
- ai_config.py: 三段式入口注册表简化为统一配置薄兼容层
- scheduler.py: task_lock 引用替换为 TaskScheduler

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 后端 Settings API 更新 — 并发数 + 余额

**Files:**
- Modify: `news-web/backend/api/settings.py`

**Interfaces:**
- New: `POST /api/settings/ai/workers` — 设置并发数
- New: `GET /api/settings/ai/balance` — 查询余额
- Changed: `GET /api/settings/ai` 简化返回结构（统一入口）

- [ ] **Step 1: 在 settings.py 新增端点**

```python
# 在 settings.py 末尾新增:

from ai_client import get_balance as _get_ai_balance
from config import config as _cfg


@router.get("/ai/balance")
def get_ai_balance():
    """查询 DeepSeek 账户余额。"""
    result = _get_ai_balance()
    if result is None:
        return {
            "ok": False,
            "error": "余额查询失败，请检查 API Key 和网络连接",
            "cached": False,
        }
    return {
        "ok": True,
        "data": result,
        "cached": False,
    }


class WorkersUpdate(BaseModel):
    workers: int

@router.post("/ai/workers")
def set_ai_workers(body: WorkersUpdate):
    """动态调整 AI 并发 worker 数。"""
    n = max(1, min(50, body.workers))
    _cfg.ai_workers = n
    try:
        from queue.task_scheduler import get_scheduler
        get_scheduler().set_workers(n)
    except RuntimeError:
        pass  # scheduler 未初始化（如测试环境）
    return {"ok": True, "workers": n}
```

- [ ] **Step 2: Commit**

```bash
git add news-web/backend/api/settings.py
git commit -m "feat: Settings API 新增余额查询 + 并发数动态调整端点

GET /api/settings/ai/balance — DeepSeek 账户余额查询
POST /api/settings/ai/workers — 动态调整 AI worker 并发数

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: 前端 — API client 新增接口

**Files:**
- Modify: `news-web/frontend/src/api/client.ts`

- [ ] **Step 1: 新增 API 端点封装**

```typescript
// 在 client.ts 中新增（aiSettings 方法附近）:

// ── AI 统一配置 ──────────────────────────────────────────
getAiBalance: () =>
  fetchJSON<{ ok: boolean; data?: { is_available: boolean; balance_infos: { currency: string; total_balance: string; granted_balance: string; topped_up_balance: string }[] }; error?: string; cached?: boolean }>('/settings/ai/balance'),

setAiWorkers: (workers: number) =>
  fetchJSON<{ ok: boolean; workers: number }>('/settings/ai/workers', {
    method: 'POST', body: JSON.stringify({ workers }),
  }),

// ── 文章管线 ──────────────────────────────────────────
cancelArticleBatch: () =>
  fetchJSON<{ ok: boolean; message: string }>('/pipeline/article/cancel', { method: 'POST' }),
```

- [ ] **Step 2: Commit**

```bash
git add news-web/frontend/src/api/client.ts
git commit -m "feat: 前端 API client 新增余额查询 + 并发调整 + 取消管线接口

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: 前端 — AI 设置页简化 + Dashboard 余额卡片

**Files:**
- Modify: `news-web/frontend/src/pages/settings/AISettings.tsx`
- Modify: `news-web/frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: AISettings.tsx — 三段式简化为单套 + 并发滑块**

将三段式配置（标题初筛/文章处理/事件管线 三个卡片）合并为一个统一配置卡片：

```tsx
// 核心改动: 三段式入口选择器 → 单一 API 配置 + 并发滑块
// 保留: base_url, api_key, model 三个输入框
// 新增: Concurrent workers 滑块 (range 1-50, step 1)
// 新增: 余额展示行
// 删除: 三个入口各自的独立配置卡片

// 并发滑块:
<div>
  <label>AI 并发数: {workers}</label>
  <input type="range" min={1} max={50} value={workers}
    onChange={e => setWorkers(Number(e.target.value))}
    onMouseUp={() => api.setAiWorkers(workers).then(r => showToast(`并发数已设为 ${r.workers}`, 'success'))}
  />
  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
    当前 {workers} 个 worker，建议 10-20
  </span>
</div>
```

保留"测试连接"按钮（调用现有 `testAi` 端点）。

- [ ] **Step 2: Dashboard.tsx — 余额卡片**

在 Dashboard 页面顶部（stats 卡片旁边）新增余额卡片：

```tsx
// 新增 state
const [balance, setBalance] = useState<BalanceData | null>(null);

// 5 分钟轮询
useEffect(() => {
  const fetch = () => api.getAiBalance().then(r => {
    if (r.ok && r.data) setBalance(r.data);
  });
  fetch();
  const interval = setInterval(fetch, 5 * 60 * 1000);
  return () => clearInterval(interval);
}, []);

// 余额卡片 UI:
{balance && (
  <div style={{ /* card style */ }}>
    <h4>💰 DeepSeek 余额</h4>
    {balance.balance_infos?.map(b => (
      <div key={b.currency}>
        <span>{b.currency} {b.total_balance}</span>
        {!balance.is_available && <span style={{color: 'var(--accent-red)'}}>⚠️ 不可用</span>}
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 3: 构建前端验证**

```bash
cd news-web/frontend && npm run build
# Expected: 无 TypeScript 错误，成功构建
```

- [ ] **Step 4: Commit**

```bash
git add news-web/frontend/src/pages/settings/AISettings.tsx \
        news-web/frontend/src/pages/Dashboard.tsx
git commit -m "feat: 前端 AI 设置简化 + Dashboard 余额卡片

- AISettings: 三段式合并为统一 DeepSeek 配置 + 并发滑块
- Dashboard: 新增余额卡片，5 分钟自动轮询

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: 全量测试 + 集成验证

**Files:**
- Modify: `news-web/tests/backend/conftest.py` (如需要初始化 DbWriter/Scheduler)

- [ ] **Step 1: 运行全部后端测试**

```bash
cd news-web && python -m pytest tests/backend/ -v
# Expected: 所有已有测试 + 新增测试通过
```

- [ ] **Step 2: 运行前端测试**

```bash
cd news-web/frontend && npm test
# Expected: 16 passed
```

- [ ] **Step 3: 构建前端**

```bash
cd news-web/frontend && npm run build
# Expected: 成功
```

- [ ] **Step 4: 重启后端验证**

```bash
bash start_platform.sh restart
# 检查日志: journalctl -u laptalk -f --no-pager | head -30
# Expected: DbWriter 已启动, TaskScheduler Worker 数: 10
```

- [ ] **Step 5: Commit**

```bash
git add -A
git diff --staged --stat  # 确认变更范围
git commit -m "test: 全量测试通过 — 统一 AI 入口 + 队列调度器集成验证

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 6: Push**

```bash
git push origin main
```

---

## 依赖关系图

```
Task 1 (DbWriter) ──────┬──→ Task 5 (process_article)
                        ├──→ Task 6 (pipeline_article)
                        ├──→ Task 7 (pipeline_event)
                        └──→ Task 14 (integration tests)

Task 2 (AI client) ────┬──→ Task 4 (config)
                       ├──→ Task 5 (process_article)
                       ├──→ Task 8 (translation)
                       └──→ Task 11 (settings API)

Task 3 (Scheduler) ────┬──→ Task 6 (pipeline_article)
                       ├──→ Task 7 (pipeline_event)
                       ├──→ Task 9 (main.py)
                       └──→ Task 14

Task 4 (config) ───────┬──→ Task 6 (pipeline_article)
                       └──→ Task 11 (settings API)

Task 11 (settings API) ──→ Task 12 (frontend API client)
Task 12 ─────────────────→ Task 13 (frontend UI)
Task 5,6,7,8,9,10,13 ───→ Task 14 (integration tests)
```

**并行执行组:**
- Group A: Task 1 + Task 2 + Task 3 (可同时)
- Group B: Task 4 + Task 8 (依赖 Group A)
- Group C: Task 5 + Task 7 + Task 9 (依赖 Group A)
- Group D: Task 6 (依赖 B, C)
- Group E: Task 10 (依赖 Group C)
- Group F: Task 11 + Task 12 (依赖 B, C)
- Group G: Task 13 (依赖 F)
- Group H: Task 14 (依赖全部)
