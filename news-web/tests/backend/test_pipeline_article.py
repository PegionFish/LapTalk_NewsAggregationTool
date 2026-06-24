"""文章管线测试"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_process_single_article_not_found():
    """请求不存在的文章应返回 ok=False"""
    r = client.post("/api/pipeline/article/99999/process")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] == False
    assert "error" in data


def test_get_article_status_idle():
    """空闲状态下 status 端点返回 running=False"""
    r = client.get("/api/pipeline/article/status")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] == False


def test_start_batch_process_response():
    """批量处理启动应返回 ok 或有意义的错误消息"""
    r = client.post("/api/pipeline/article/batch-process")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
    assert "message" in data
    # Either starts successfully or reports already running
    assert data["ok"] == True or "已在运行" in str(data.get("message", "")) or "无法启动" in str(data.get("message", ""))
