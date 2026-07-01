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

    def _process(self, item, conn):
        """处理一个队列项。"""
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

    def _drain(self, conn):
        """排空队列中所有剩余请求（stop 后调用）。"""
        while True:
            try:
                item = self._queue.get(timeout=1)
            except Empty:
                break
            if item is None:
                break
            self._process(item, conn)

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

            self._process(item, conn)

        # stop 后排空剩余请求（_stop_event 设置后主循环退出，但队列可能还有未处理的项）
        self._drain(conn)

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
