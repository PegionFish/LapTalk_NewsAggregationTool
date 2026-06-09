import os, sys, pytest, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from db.news_db import NewsDB
from db.migrations import ensure_schema

@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / 'test.db')

@pytest.fixture
def news_db(test_db_path):
    db = NewsDB(test_db_path)
    # Enable WAL
    with db._conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(test_db_path)
    # Seed test data
    db.save_articles('rss_news', [
        {'title': 'Intel Nova Lake leak', 'source': 'Guru3D', 'url': 'https://test.com/1', 'metadata': {}},
        {'title': 'Intel Nova Lake CPU details', 'source': 'Wccftech', 'url': 'https://test.com/2', 'metadata': {}},
        {'title': 'AMD RDNA 4 architecture', 'source': 'TechPowerUp', 'url': 'https://test.com/3', 'metadata': {}},
    ])
    db.link_articles_to_events()
    yield db
