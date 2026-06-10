"""User model and migration."""
import sqlite3
from datetime import datetime

USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    role        TEXT DEFAULT 'user' CHECK(role IN ('admin', 'user', 'viewer')),
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""

def ensure_users_table(db_path: str):
    """Create users table if it doesn't exist. Idempotent."""
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.executescript(USERS_SQL)
    conn.commit()
    conn.close()
