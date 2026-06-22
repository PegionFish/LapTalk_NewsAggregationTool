import sqlite3

LOGIC_CHAINS_SQL = """
CREATE TABLE IF NOT EXISTS logic_chains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT DEFAULT 'human'
);

CREATE TABLE IF NOT EXISTS chain_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id),
    position INTEGER NOT NULL,
    note     TEXT DEFAULT '',
    UNIQUE(chain_id, event_id)
);

CREATE TABLE IF NOT EXISTS chain_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    child_chain_id  INTEGER NOT NULL REFERENCES logic_chains(id),
    position        INTEGER NOT NULL,
    UNIQUE(parent_chain_id, child_chain_id)
);

-- Query performance indexes
CREATE INDEX IF NOT EXISTS idx_chain_events_chain_pos ON chain_events(chain_id, position);
CREATE INDEX IF NOT EXISTS idx_chain_relations_parent_pos ON chain_relations(parent_chain_id, position);

-- Schema version tracking for phased migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version   INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def ensure_schema(db_path: str):
    """Run migrations on the target database. Idempotent — uses IF NOT EXISTS."""
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.executescript(LOGIC_CHAINS_SQL)
    # Ensure baseline version is recorded (idempotent: INSERT OR IGNORE)
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
    conn.commit()
    conn.close()

    # ── v2 迁移：评分从 0~1 改为百分制 0~100 ──────────────
    conn = sqlite3.connect(db_path)
    cur_ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    if cur_ver < 2:
        try:
            conn.execute("""
                UPDATE news_articles SET priority_score = ROUND(priority_score * 100, 0)
                WHERE priority_score > 0 AND priority_score <= 1
            """)
            conn.execute("""
                UPDATE news_articles SET ai_priority_score = ROUND(ai_priority_score * 100, 0)
                WHERE ai_priority_score > 0 AND ai_priority_score <= 1
            """)
        except sqlite3.OperationalError:
            pass  # news_articles 表尚未创建，由 _init_db 创建后再处理
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2)")
        conn.commit()
    conn.close()

    # ── v3 迁移：article_comments 添加 rating 列 ─────────
    conn = sqlite3.connect(db_path)
    cur_ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    if cur_ver < 3:
        try:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(article_comments)").fetchall()]
            if 'rating' not in cols:
                conn.execute("ALTER TABLE article_comments ADD COLUMN rating INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # article_comments 表尚未创建
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (3)")
        conn.commit()
    conn.close()

    # ── v4 迁移：news_articles 添加 retry_count 列（死链温和判定）─
    conn = sqlite3.connect(db_path)
    cur_ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    if cur_ver < 4:
        try:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(news_articles)").fetchall()]
            if 'retry_count' not in cols:
                conn.execute("ALTER TABLE news_articles ADD COLUMN retry_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # news_articles 表尚未创建
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (4)")
        conn.commit()
    conn.close()

    # Users table migration
    from auth.models import ensure_users_table
    ensure_users_table(db_path)

    # Audit log migration
    from db.audit import ensure_audit_table
    ensure_audit_table(db_path)

    # ── fetch_logs: 抓取历史记录表 ──────────────────────
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name     TEXT    NOT NULL,
            source_type     TEXT    NOT NULL,
            articles_fetched INTEGER DEFAULT 0,
            articles_new    INTEGER DEFAULT 0,
            status          TEXT    DEFAULT 'ok',
            error_msg       TEXT,
            duration_ms     INTEGER,
            started_at      TEXT    NOT NULL,
            finished_at     TEXT,
            run_type        TEXT    DEFAULT 'scheduled'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fetch_logs_source
        ON fetch_logs(source_name, started_at)
    """)
    conn.commit()
    conn.close()

    # ── v5 迁移：news_articles 拆分为 news_articles + trending_items ──
    conn = sqlite3.connect(db_path)
    cur_ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    conn.close()
    if cur_ver < 5:
        from db.migration_v5 import run_migration
        success = run_migration(db_path)
        if not success:
            raise RuntimeError(
                "v5 迁移（news_articles 表拆分）失败！"
                "请检查日志并手动恢复数据库: "
                f"cp {db_path}.pre_migration_backup {db_path}"
            )
