"""Notification system — review reminders, event updates, digest preferences."""
import sqlite3, json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from config import config
from auth.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

NOTIFICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS notification_prefs (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id),
    email       TEXT DEFAULT '',
    digest_enabled INTEGER DEFAULT 0,
    review_reminders INTEGER DEFAULT 1,
    event_updates INTEGER DEFAULT 1,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    type        TEXT NOT NULL,          -- 'review_needed','event_update','digest'
    title       TEXT NOT NULL,
    body        TEXT DEFAULT '',
    entity_type TEXT DEFAULT '',
    entity_id   INTEGER,
    read        INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notif_user_read ON notifications(user_id, read);
CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at DESC);
"""

def ensure_notif_tables(db_path: str):
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.executescript(NOTIFICATIONS_SQL)
    conn.commit()
    conn.close()

# ── Preferences ────────────────────────────────────────────

class PrefsUpdate(BaseModel):
    email: str = ''
    digest_enabled: bool = False
    review_reminders: bool = True
    event_updates: bool = True

@router.get("/prefs")
def get_prefs(user: dict = Depends(get_current_user)):
    ensure_notif_tables(config.db_path)
    conn = sqlite3.connect(config.db_path)
    row = conn.execute(
        "SELECT email, digest_enabled, review_reminders, event_updates FROM notification_prefs WHERE user_id=?",
        (user['id'],)
    ).fetchone()
    conn.close()
    if row:
        return {'email': row[0], 'digest_enabled': bool(row[1]), 'review_reminders': bool(row[2]), 'event_updates': bool(row[3])}
    return {'email': '', 'digest_enabled': False, 'review_reminders': True, 'event_updates': True}

@router.put("/prefs")
def update_prefs(body: PrefsUpdate, user: dict = Depends(get_current_user)):
    ensure_notif_tables(config.db_path)
    conn = sqlite3.connect(config.db_path)
    now = datetime.utcnow().isoformat(timespec='seconds')
    conn.execute("""
        INSERT INTO notification_prefs (user_id, email, digest_enabled, review_reminders, event_updates, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            email=excluded.email,
            digest_enabled=excluded.digest_enabled,
            review_reminders=excluded.review_reminders,
            event_updates=excluded.event_updates,
            updated_at=excluded.updated_at
    """, (user['id'], body.email, int(body.digest_enabled),
          int(body.review_reminders), int(body.event_updates), now))
    conn.commit()
    conn.close()
    return {'ok': True}

# ── Notifications ──────────────────────────────────────────

@router.get("")
def list_notifications(
    limit: int = 20,
    unread_only: bool = False,
    user: dict = Depends(get_current_user)
):
    ensure_notif_tables(config.db_path)
    conn = sqlite3.connect(config.db_path)
    where = "user_id = ?"
    params = [user['id']]
    if unread_only:
        where += " AND read = 0"

    rows = conn.execute(f"""
        SELECT id, type, title, body, entity_type, entity_id, read, created_at
        FROM notifications WHERE {where} ORDER BY created_at DESC LIMIT ?
    """, params + [limit]).fetchall()

    unread = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user['id'],)
    ).fetchone()[0]
    conn.close()

    return {
        'notifications': [
            {'id': r[0], 'type': r[1], 'title': r[2], 'body': r[3],
             'entity_type': r[4], 'entity_id': r[5], 'read': bool(r[6]), 'created_at': r[7]}
            for r in rows
        ],
        'unread_count': unread,
    }

@router.post("/{notif_id}/read")
def mark_read(notif_id: int, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(config.db_path)
    conn.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (notif_id, user['id']))
    conn.commit()
    conn.close()
    return {'ok': True}

@router.post("/read-all")
def mark_all_read(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(config.db_path)
    conn.execute("UPDATE notifications SET read=1 WHERE user_id=? AND read=0", (user['id'],))
    conn.commit()
    conn.close()
    return {'ok': True}

# ── Helper: create notification (used by other modules) ────

def create_notification(db_path: str, user_id: int, type_: str, title: str,
                        body: str = '', entity_type: str = '', entity_id: int | None = None):
    """Create a notification for a user. Safe to call from any API module."""
    if not db_path or not user_id:
        return
    ensure_notif_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO notifications (user_id, type, title, body, entity_type, entity_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, type_, title, body, entity_type, entity_id or 0,
          datetime.utcnow().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()
