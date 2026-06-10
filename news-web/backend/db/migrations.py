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
