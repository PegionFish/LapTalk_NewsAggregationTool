"""
数据库连接工具 — 统一连接配置，防止 WAL 并发写锁导致数据丢失。

背景:
  SQLite WAL 模式允许多读单写。AI 批量任务和数据采集 pipeline
  设计上可并行运行，两者同时写入时，第二个写者默认仅等待 5 秒即抛
  "database is locked"。这会导致耗时数分钟的 AI 分析结果因 DB 写入失败而丢弃。

  本模块将超时提升至 30 秒，并在应用层增加指数退避重试，作为 C 层超时的安全网。

用法:
    from utils.db import get_db_connection, safe_commit
    conn = get_db_connection(config.db_path)
    ...
    safe_commit(conn)
    conn.close()
"""
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

# 默认超时：30 秒等待 + 最多 3 次应用层指数退避重试（2s/4s/8s）
DEFAULT_TIMEOUT = 30.0
DEFAULT_COMMIT_RETRIES = 3
DEFAULT_COMMIT_BASE_DELAY = 2.0


def get_db_connection(db_path: str, timeout: float = DEFAULT_TIMEOUT, wal: bool = True) -> sqlite3.Connection:
    """
    创建带超时配置的 SQLite 连接，从根源缓解并发写锁冲突。

    参数:
        db_path: 数据库文件路径
        timeout: 等待锁释放的最长时间（秒），默认 30s。底层设置 sqlite3_busy_timeout
        wal: 是否确认 WAL 模式已启用（默认 True，幂等操作）

    返回:
        已配置 sqlite3.Connection 实例
    """
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")  # 幂等 — 已启用 WAL 的数据库不报错
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def safe_commit(conn: sqlite3.Connection, max_retries: int = DEFAULT_COMMIT_RETRIES,
                base_delay: float = DEFAULT_COMMIT_BASE_DELAY) -> None:
    """
    带指数退避重试的 commit，应对 WAL 并发写锁冲突。

    C 层 busy_timeout（30s）耗尽后，应用层再重试 max_retries 次。
    延迟序列: base_delay → 2×base_delay → 4×base_delay → …
    默认总计: 30 + 2 + 4 + 8 ≈ 44 秒等待窗口。

    参数:
        conn: 数据库连接
        max_retries: 最大重试次数（默认 3 次）
        base_delay: 首次重试前等待秒数（默认 2s）

    抛出:
        sqlite3.OperationalError: 所有重试均失败时
    """
    for attempt in range(max_retries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[DB] commit 重试 {attempt + 1}/{max_retries}, 等待 {delay:.0f}s: {e}")
                time.sleep(delay)
            else:
                raise
