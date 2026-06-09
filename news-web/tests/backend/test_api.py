import pytest, json, os
from fastapi.testclient import TestClient
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

# Disable scheduler during tests
os.environ['NEWS_WEB_TESTING'] = '1'

from main import app
from config import config

@pytest.fixture
def client(test_db_path):
    config.db_path = test_db_path
    with TestClient(app) as c:
        yield c

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
    resp = client.get("/api/articles")
    data = resp.json()
    assert len(data["articles"]) >= 3
    assert data["total"] >= 3

def test_search_articles(client, news_db):
    resp = client.get("/api/articles?q=Nova")
    data = resp.json()
    assert len(data["articles"]) >= 2

def test_get_article(client, news_db):
    # Get first article ID from the list
    resp = client.get("/api/articles?limit=1")
    articles = resp.json().get("articles", [])
    if articles:
        article_id = articles[0]["id"]
        resp = client.get(f"/api/articles/{article_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == article_id

def test_update_article(client, news_db):
    resp = client.patch("/api/articles/1", json={"priority_label": "high"})
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
