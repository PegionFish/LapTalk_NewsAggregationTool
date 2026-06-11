import os, sys, pytest, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from db.news_db import NewsDB
from db.migrations import ensure_schema
from config import config, AppConfig

# ── 全局防护：测试期间禁止 config.save() 写入磁盘 ──────────
_original_save = AppConfig.save

def _noop_save(self):
    pass  # 测试期间不持久化配置变更

@pytest.fixture(autouse=True)
def _protect_config():
    """全局自动固件：mock 掉 config.save()，防止测试把临时路径写入 config.json"""
    AppConfig.save = _noop_save
    yield
    AppConfig.save = _original_save

@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / 'test.db')

@pytest.fixture
def client(test_db_path):
    # 直接修改 _data 绕过 db_path.setter 的自动 save()，
    # 避免测试路径污染 config.json
    config._data['db_path'] = test_db_path
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
    config._data['db_path'] = ''  # 恢复默认

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
