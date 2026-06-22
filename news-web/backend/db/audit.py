"""
Audit log for multi-user collaboration tracking.
Logs create/update/delete operations on news_articles, events, chains, and relations.
"""
import sqlite3, json
from datetime import datetime

AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT DEFAULT 'anonymous',
    action      TEXT NOT NULL,          -- 'create','update','delete','merge','split','confirm','reject'
    entity_type TEXT NOT NULL,          -- 'article','event','chain','relation'
    entity_id   INTEGER,
    entity_title TEXT DEFAULT '',
    details     TEXT DEFAULT '{}',      -- JSON blob with before/after or extra context
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
"""

def ensure_audit_table(db_path: str):
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.executescript(AUDIT_SQL)
    conn.commit()
    conn.close()


def log_action(db_path: str, user_id: int | None, username: str,
               action: str, entity_type: str, entity_id: int,
               entity_title: str = '', details: dict | None = None):
    """Record an audit log entry."""
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO audit_log (user_id, username, action, entity_type, entity_id, entity_title, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, action, entity_type, entity_id, entity_title,
         json.dumps(details or {}, ensure_ascii=False),
         datetime.utcnow().isoformat(timespec='seconds'))
    )
    conn.commit()
    conn.close()


def get_audit_log(db_path: str, limit: int = 50, entity_type: str = '',
                  user_id: int | None = None) -> list:
    """Get recent audit log entries."""
    if not db_path:
        return []
    conn = sqlite3.connect(db_path)

    clauses = ["1=1"]
    params = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)

    where = " AND ".join(clauses)
    rows = conn.execute(f"""
        SELECT id, user_id, username, action, entity_type, entity_id, entity_title, details, created_at
        FROM audit_log WHERE {where} ORDER BY created_at DESC LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()

    return [
        {'id': r[0], 'user_id': r[1], 'username': r[2], 'action': r[3],
         'entity_type': r[4], 'entity_id': r[5], 'entity_title': r[6],
         'details': json.loads(r[7]) if r[7] else {}, 'created_at': r[8]}
        for r in rows
    ]
