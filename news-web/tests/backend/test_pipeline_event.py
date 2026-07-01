"""事件管线测试

注意：test_start_nightly_response 提交后台任务后不等待完成即返回，
teardown_module 的 shutdown(timeout=5) 不能保证清理在 5s 后仍运行的
daemon 线程，可能导致孤儿 DB/AI 连接泄漏到后续测试。这是当前架构的局限，
可接受。"Todo: 后台任务应提供同步确认机制。""
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from scheduler.task_scheduler import init_scheduler, get_scheduler

# 初始化 TaskScheduler（pipeline_event 端点依赖 get_scheduler()）
init_scheduler(max_workers=5)

client = TestClient(app)


def teardown_module(module):
    try:
        get_scheduler().shutdown()
    except Exception:
        pass


def test_get_event_status_idle():
    """空闲状态下 event status 返回 running=False"""
    r = client.get("/api/pipeline/event/status")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] == False
    assert "steps" in data


def test_start_nightly_response():
    """启动夜间管线应返回 ok"""
    r = client.post("/api/pipeline/event/nightly")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data


def test_recluster_status_idle():
    """重聚类空闲状态"""
    r = client.get("/api/pipeline/event/recluster/status")
    assert r.status_code == 200
    assert "running" in r.json()


def test_summarize_status_idle():
    """摘要空闲状态"""
    r = client.get("/api/pipeline/event/summarize/status")
    assert r.status_code == 200
    assert "running" in r.json()


def test_build_chains_status_idle():
    """逻辑链构建空闲状态"""
    r = client.get("/api/pipeline/event/build-chains/status")
    assert r.status_code == 200
    assert "running" in r.json()


def test_cancel_unknown_op():
    """取消未知操作应返回错误"""
    r = client.post("/api/pipeline/event/unknown_op/cancel")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] == False
