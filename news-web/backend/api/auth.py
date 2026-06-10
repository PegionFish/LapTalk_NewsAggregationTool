"""Auth API — login, register, session check."""
import sqlite3
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime

from config import config
from auth.auth import (
    hash_password, verify_password, create_token,
    get_current_user, get_user_by_id,
)
from auth.models import ensure_users_table

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ''

@router.post("/register")
def register(body: RegisterRequest):
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    if len(body.username) < 3:
        raise HTTPException(400, "username_too_short")
    if len(body.password) < 6:
        raise HTTPException(400, "password_too_short")

    ensure_users_table(config.db_path)
    conn = sqlite3.connect(config.db_path)

    existing = conn.execute("SELECT id FROM users WHERE username=?", (body.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, "username_taken")

    now = datetime.utcnow().isoformat(timespec='seconds')
    password_hash = hash_password(body.password)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role, created_at) VALUES (?, ?, ?, 'user', ?)",
        (body.username, password_hash, body.display_name, now)
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = create_token(user_id, body.username, 'user')
    return {
        'token': token,
        'user': {'id': user_id, 'username': body.username, 'display_name': body.display_name, 'role': 'user'},
    }

@router.post("/login")
def login(body: LoginRequest):
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")

    conn = sqlite3.connect(config.db_path)
    row = conn.execute(
        "SELECT id, username, password_hash, display_name, role FROM users WHERE username=?",
        (body.username,)
    ).fetchone()

    if not row or not verify_password(body.password, row[2]):
        conn.close()
        raise HTTPException(401, "invalid_credentials")

    now = datetime.utcnow().isoformat(timespec='seconds')
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (now, row[0]))
    conn.commit()
    conn.close()

    token = create_token(row[0], row[1], row[4])
    return {
        'token': token,
        'user': {'id': row[0], 'username': row[1], 'display_name': row[3], 'role': row[4]},
    }

@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Return the current authenticated user."""
    return {'user': user}
