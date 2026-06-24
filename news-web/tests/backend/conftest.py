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

def _precreate_tables(db_path: str):
    """在 TestClient 启动 lifespan 之前预创建核心表，使 ensure_schema 能安全运行。"""
    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            url TEXT DEFAULT '',
            category TEXT NOT NULL,
            published_date TEXT DEFAULT '',
            fetched_at TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            keywords TEXT DEFAULT '[]',
            priority_score REAL DEFAULT 0.0,
            priority_label TEXT DEFAULT 'unset',
            human_verified INTEGER DEFAULT 0,
            human_tags TEXT DEFAULT '[]',
            local_path TEXT DEFAULT '',
            content_fetched_at TEXT,
            text_content TEXT DEFAULT '',
            translated_content TEXT DEFAULT '',
            content_lang TEXT DEFAULT '',
            content_status TEXT DEFAULT 'pending',
            translated_at TEXT,
            ai_summary TEXT DEFAULT '',
            ai_analyzed INTEGER DEFAULT 0,
            human_processed INTEGER DEFAULT 0,
            ai_keywords TEXT DEFAULT '',
            ai_category TEXT DEFAULT '',
            ai_tags TEXT DEFAULT '',
            ai_priority_score REAL DEFAULT 0.0,
            ai_filtered INTEGER DEFAULT 0,
            topic_category TEXT DEFAULT '',
            ai_cleaned_content TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            UNIQUE(title, source, url)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
            user_id INTEGER,
            username TEXT DEFAULT 'anonymous',
            parent_id INTEGER REFERENCES article_comments(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            rating INTEGER DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            first_seen DATE NOT NULL,
            last_seen DATE NOT NULL,
            article_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            priority_label TEXT DEFAULT 'medium'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_article_events (
            article_id INTEGER REFERENCES news_articles(id),
            event_id INTEGER REFERENCES events(id),
            relevance REAL DEFAULT 1.0,
            PRIMARY KEY (article_id, event_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS human_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER REFERENCES news_articles(id),
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT NOT NULL,
            applied INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS event_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_event_id INTEGER NOT NULL REFERENCES events(id),
            to_event_id INTEGER NOT NULL REFERENCES events(id),
            relation TEXT NOT NULL
                CHECK(relation IN ('before','after','update','spawn','related')),
            created_by TEXT DEFAULT 'human',
            created_at TEXT NOT NULL,
            UNIQUE(from_event_id, to_event_id, relation)
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / 'test.db')

@pytest.fixture
def client(test_db_path):
    _precreate_tables(test_db_path)
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
    db.save_news_articles('rss_news', [
        {'title': 'Intel Nova Lake leak', 'source': 'Guru3D', 'url': 'https://test.com/1', 'metadata': {}},
        {'title': 'Intel Nova Lake CPU details', 'source': 'Wccftech', 'url': 'https://test.com/2', 'metadata': {}},
        {'title': 'AMD RDNA 4 architecture', 'source': 'TechPowerUp', 'url': 'https://test.com/3', 'metadata': {}},
    ])
    # 标记为已抓取并直接创建测试事件（link_articles_to_events 已于 2026-06-24 废弃）
    with db._conn() as conn:
        conn.execute("UPDATE news_articles SET content_status='fetched', ai_keywords='[]' WHERE content_status='pending' OR content_status IS NULL")
        conn.commit()
        # 直接创建事件和文章-事件关联，替代废弃的 bigram 聚类
        conn.execute("INSERT INTO events (id, title, first_seen, last_seen, article_count, status) VALUES (1, 'Intel Nova Lake series', '2026-06-10', '2026-06-12', 2, 'active')")
        conn.execute("INSERT INTO events (id, title, first_seen, last_seen, article_count, status) VALUES (2, 'AMD RDNA 4 architecture', '2026-06-11', '2026-06-11', 1, 'active')")
        conn.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (1, 1)")
        conn.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (2, 1)")
        conn.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (3, 2)")
        conn.commit()
    yield db
