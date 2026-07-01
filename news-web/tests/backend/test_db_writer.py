import threading
import sqlite3
import pytest
from dbwriter.db_writer import DbWriter, WriteRequest


def test_db_writer_submit_and_ack(tmp_path):
    """提交写请求后 Writer 执行并设置 event"""
    db_path = str(tmp_path / "test.db")
    writer = DbWriter(db_path)
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

    # 验证数据已写入（使用相同文件路径，确保读到 Writer 写入的内容）
    conn = sqlite3.connect(db_path)
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
