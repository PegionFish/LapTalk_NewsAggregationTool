import pytest, json, os, sqlite3
from datetime import datetime
from fastapi.testclient import TestClient
from types import SimpleNamespace
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

# Disable scheduler during tests
os.environ['NEWS_WEB_TESTING'] = '1'

from main import app
from config import config
from utils.text import extract_text_from_html
from ai_client import _ai_json, analyze_article, chat, extract_keywords_ai
# 从 conftest 导入预创建表函数
from conftest import _precreate_tables

@pytest.fixture
def client(test_db_path):
    # 预创建核心表，确保 lifespan 中的 ensure_schema 不会因表不存在而报错
    _precreate_tables(test_db_path)
    # 直接操作 _data 绕过 setter，避免测试路径写入 config.json
    config._data['db_path'] = test_db_path
    with TestClient(app) as c:
        yield c
    config._data['db_path'] = ''  # 恢复

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_stats(client, news_db):
    resp = client.get("/api/stats")
    data = resp.json()
    assert data["articles"] >= 3
    assert data["events"] >= 1
    assert "rss_news" in data["by_category"]

def test_list_articles(client, news_db):
    resp = client.get("/api/news")
    data = resp.json()
    assert len(data["articles"]) >= 3
    assert data["total"] >= 3

def test_search_articles(client, news_db):
    resp = client.get("/api/news?q=Nova")
    data = resp.json()
    assert len(data["articles"]) >= 2

def test_get_article(client, news_db):
    # Get first article ID from the list
    resp = client.get("/api/news?limit=1")
    articles = resp.json().get("articles", [])
    if articles:
        article_id = articles[0]["id"]
        resp = client.get(f"/api/news/{article_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == article_id

def test_update_article(client, news_db):
    resp = client.patch("/api/news/1", json={"priority_label": "high"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

def test_list_events(client, news_db):
    resp = client.get("/api/events")
    data = resp.json()
    assert len(data["events"]) >= 1

def test_get_event(client, news_db):
    # Get first event ID
    resp = client.get("/api/events?limit=1")
    events = resp.json().get("events", [])
    if events:
        event_id = events[0]["id"]
        resp = client.get(f"/api/events/{event_id}")
        assert resp.status_code == 200
        assert "articles" in resp.json()

def test_create_chain(client, news_db):
    resp = client.post("/api/chains", json={"title": "Test Chain", "event_ids": [1, 2]})
    assert resp.status_code == 200
    assert resp.json()["id"] > 0

def test_list_chains(client, news_db):
    client.post("/api/chains", json={"title": "Chain 1"})
    resp = client.get("/api/chains")
    assert len(resp.json()["chains"]) >= 1

def test_delete_chain(client, news_db):
    r = client.post("/api/chains", json={"title": "To Delete"})
    cid = r.json()["id"]
    resp = client.delete(f"/api/chains/{cid}")
    assert resp.status_code == 200

def test_merge_events(client, news_db):
    resp = client.post("/api/events/1/merge", json={"target_event_id": 2})
    assert resp.status_code == 200

def test_split_event(client, news_db):
    # Get event detail to find article ids
    resp = client.get("/api/events/1")
    articles = resp.json().get("articles", [])
    if len(articles) >= 2:
        ids = [a["id"] for a in articles[:2]]
        resp = client.post("/api/events/1/split", json={"article_ids": ids, "new_event_title": "Split Event"})
        assert resp.status_code == 200
        assert resp.json()["new_event_id"] > 0

def test_create_relation(client, news_db):
    resp = client.post("/api/relations", json={"from_event_id": 1, "to_event_id": 2, "relation": "related"})
    assert resp.status_code == 200

def test_settings(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert "db_path" in resp.json()

    resp = client.put("/api/settings", json={"user_agent": "test-agent"})
    assert resp.status_code == 200
    assert resp.json()["user_agent"] == "test-agent"


def test_extract_text_keeps_full_text_for_deepseek_context():
    """正文提取应保留 DeepSeek 160K 上下文所需的长正文。"""
    body = " ".join(["word"] * 15000)
    html = f"<html><body><article>{body}</article></body></html>"

    text = extract_text_from_html(html)

    assert len(text) > 50000
    assert text.endswith("word word")


def test_analyze_article_sends_full_text(monkeypatch):
    """单篇分析应把完整正文放入分析请求，而不是只截取前 8000 字。"""
    captured = {}
    text = "A" * 9000

    class FakeCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="分析完成"))])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("ai_client.get_client", lambda: FakeClient())

    result = analyze_article("测试标题", text)

    assert result == "分析完成"
    assert "正文：" in captured["messages"][1]["content"]
    assert "思考流程" in captured["messages"][1]["content"]
    assert len(captured["messages"][1]["content"]) > 9000


def test_chat_sends_deep_thinking_params(monkeypatch):
    """chat() 应默认启用深度思考，但不强制 JSON 格式（JSON 格式仅 _ai_json() 使用）。"""
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("ai_client.get_client", lambda: FakeClient())
    config._data['ai_enable_thinking'] = True
    config._data['ai_thinking_budget'] = 32768
    config._data['ai_json_response_format'] = True

    result = chat("分析这篇文章", max_tokens=128)

    assert result == "OK"
    assert captured["extra_body"]["thinking"] == {"type": "enabled"}
    assert captured["extra_body"]["reasoning_effort"] == "high"
    assert "response_format" not in captured  # chat() 不再强制 JSON 格式


def test_ai_json_strips_markdown_and_uses_json_object(monkeypatch):
    """结构化 AI 调用应使用 json_object 并能解析 markdown 包裹。"""
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="```json\n{\"ok\": true}\n```"))])

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("ai_client.get_client", lambda: FakeClient())
    config._data['ai_enable_thinking'] = True
    config._data['ai_thinking_budget'] = 32768
    config._data['ai_json_response_format'] = True

    result = _ai_json("返回 JSON", "system")

    assert result == {"ok": True}
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"]["thinking"] == {"type": "enabled"}
    assert captured["extra_body"]["reasoning_effort"] == "high"


def test_extract_keywords_ai_sends_full_text(monkeypatch):
    """关键词提取应把完整正文放入关键词请求，而不是只截取前 6000 字。"""
    captured = {}
    text = "B" * 7000

    def fake_ai_json(prompt, system_prompt, max_tokens=1024, **kwargs):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["max_tokens"] = max_tokens
        captured["kwargs"] = kwargs
        return ["GPU"]

    monkeypatch.setattr("ai_client._ai_json", fake_ai_json)

    result = extract_keywords_ai("测试标题", text, "Guru3D")

    assert result == ["GPU"]
    assert "正文：" in captured["prompt"]
    assert len(captured["prompt"]) > 7000



def test_cache_status_only_counts_ai_approved_rss_articles(client, news_db, test_db_path, tmp_path):
    """页面 HTML 缓存状态只统计 AI 已通过筛选的普通 RSS 文章。"""
    os.makedirs(tmp_path, exist_ok=True)
    config._data['content_cache_path'] = str(tmp_path)
    now = datetime.utcnow().isoformat(timespec="seconds")

    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE news_articles SET ai_filtered=1 WHERE id=1")
    conn.execute("UPDATE news_articles SET ai_filtered=0 WHERE id=2")
    conn.execute("UPDATE news_articles SET ai_filtered=-1 WHERE id=3")
    # 注意：以下 hotlist/bilibili 数据已迁移到 trending_items 表，
    # 但本测试仅验证 RSS 缓存状态计数，插入这些行不应影响结果
    conn.execute(
        """
        INSERT INTO news_articles
            (title, source, url, category, published_date, fetched_at, metadata, keywords, ai_filtered)
        VALUES (?, ?, ?, ?, '', ?, '{}', '[]', 1)
        """,
        ("Platform Hot Topic", "weibo_hotlist", "https://hot.example/1", "platform_hotlists", now),
    )
    conn.execute(
        """
        INSERT INTO news_articles
            (title, source, url, category, published_date, fetched_at, metadata, keywords, ai_filtered)
        VALUES (?, ?, ?, ?, '', ?, '{}', '[]', 1)
        """,
        ("Bilibili Video", "bilibili_hotlist", "https://bili.example/1", "bilibili_videos", now),
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/cache/status")

    assert resp.status_code == 200
    assert resp.json()["summary"]["total_news_articles"] == 1
    assert resp.json()["summary"]["with_url"] == 1
    assert resp.json()["summary"]["pending_download"] == 1
    assert resp.json()["summary"]["failed_download"] == 0
    assert resp.json()["uncached_count"] == 1
    assert [item["id"] for item in resp.json()["uncached_news_articles"]] == [1]



# ══════════════════════════════════════════════════════════════
# 数据采集监控 API 测试 (api/fetch.py)
# ══════════════════════════════════════════════════════════════

def test_fetch_overview(client, news_db):
    """overview 返回正确四级统计结构 + 缓存维度"""
    news_db.log_fetch('Guru3D', 'rss', 10, 3, 'ok', '', 1200, 'scheduled')
    resp = client.get("/api/fetch/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "rss" in data
    assert "hotlist" in data
    assert "cache" in data
    assert isinstance(data["rss"]["healthy"], int)
    assert isinstance(data["cache"]["cached_pct"], float)
    assert data["rss"]["articles_today"] >= 0


def test_fetch_sources(client, news_db):
    """sources 列表返回所有源及健康状态"""
    resp = client.get("/api/fetch/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 1
    src = data["sources"][0]
    assert "name" in src
    assert "type" in src
    assert "health" in src
    assert src["health"] in ("healthy", "degraded", "failing")


def test_fetch_source_history(client, news_db):
    """单源历史按 days 参数正确筛选"""
    news_db.log_fetch('Guru3D', 'rss', 5, 2, 'ok', '', 1000, 'scheduled')
    news_db.log_fetch('Guru3D', 'rss', 3, 0, 'failed', 'Timeout', 8000, 'scheduled')
    resp = client.get("/api/fetch/sources/Guru3D/history?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "Guru3D"
    assert len(data["history"]) >= 2


def test_fetch_source_retry_unknown(client, news_db):
    """重试不存在的源应返回错误"""
    resp = client.post("/api/fetch/sources/NonExistentSource/retry")
    assert resp.status_code in (404, 200)
    if resp.status_code == 200:
        assert resp.json().get("ok") is False


def test_fetch_source_articles(client, news_db):
    """源文章列表筛选 + 分页正确"""
    resp = client.get("/api/fetch/sources/Guru3D/news_articles?page=1&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert data["source"] == "Guru3D"
    assert data["total"] >= 1
    assert len(data["articles"]) >= 1
    art = data["articles"][0]
    assert "content_status" in art


def test_fetch_retry_article_cache(client, news_db):
    """单篇缓存重试返回 ok"""
    resp = client.post("/api/fetch/news_articles/1/retry-cache")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_fetch_batch_retry_limit(client, news_db):
    """批量重试超过 500 篇应返回错误"""
    resp = client.post("/api/fetch/news_articles/batch-retry", json={"ids": list(range(1, 510))})
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data or "error" in data


def test_fetch_failed_articles(client, news_db):
    """失败文章列表分页正确"""
    resp = client.get("/api/fetch/news_articles/failed?page=1&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert "total" in data
    assert "page" in data
