"""Auth API — login, register, session check."""
import sqlite3
from fastapi import APIRouter, HTTPException, Depends, Request
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

@router.get("/local")
def local_login(request: Request):
    """本机免密登录 — 仅允许 localhost/127.0.0.1 访问，自动创建 local_admin 账户。"""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "仅限本机访问")

    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    ensure_users_table(config.db_path)
    conn = sqlite3.connect(config.db_path)

    row = conn.execute("SELECT id, username, password_hash, display_name, role FROM users WHERE username='local_admin'").fetchone()
    if not row:
        now = datetime.utcnow().isoformat(timespec='seconds')
        password_hash = hash_password("local_admin")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, created_at) VALUES ('local_admin', ?, '本地管理员', 'admin', ?)",
            (password_hash, now)
        )
        user_id = cur.lastrowid
        conn.commit()
        row = (user_id, "local_admin", password_hash, "本地管理员", "admin")
    else:
        conn.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.utcnow().isoformat(timespec='seconds'), row[0]))
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


# ── 管理员用户管理 ──────────────────────────────────────

def _require_admin(user: dict):
    """管理员权限校验，非 admin 角色拒绝访问。"""
    if user.get('role') != 'admin':
        raise HTTPException(403, "admin_required")


@router.get("/users")
def list_users(admin: dict = Depends(get_current_user)):
    """列出所有用户（管理员专用）。"""
    _require_admin(admin)
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute(
        "SELECT id, username, display_name, role, created_at, last_login FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return {
        'users': [
            {'id': r[0], 'username': r[1], 'display_name': r[2], 'role': r[3],
             'created_at': r[4], 'last_login': r[5]}
            for r in rows
        ]
    }


class UserUpdate(BaseModel):
    role: str | None = None          # 'admin' | 'user' | 'viewer'
    display_name: str | None = None
    password: str | None = None      # 可选重置密码


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: dict = Depends(get_current_user)):
    """修改用户角色/名称/密码（管理员专用）。"""
    _require_admin(admin)
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    conn = sqlite3.connect(config.db_path)
    existing = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "user_not_found")

    if body.role is not None:
        if body.role not in ('admin', 'user', 'viewer'):
            conn.close()
            raise HTTPException(400, "invalid_role")
        conn.execute("UPDATE users SET role=? WHERE id=?", (body.role, user_id))
    if body.display_name is not None:
        conn.execute("UPDATE users SET display_name=? WHERE id=?", (body.display_name, user_id))
    if body.password is not None:
        if len(body.password) < 6:
            conn.close()
            raise HTTPException(400, "password_too_short")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (hash_password(body.password), user_id))
    conn.commit()
    conn.close()
    return {'ok': True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(get_current_user)):
    """删除用户（管理员专用）。不能删除自己。"""
    _require_admin(admin)
    if int(admin.get('sub', 0)) == user_id:
        raise HTTPException(400, "cannot_delete_self")
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")
    conn = sqlite3.connect(config.db_path)
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {'ok': True}
