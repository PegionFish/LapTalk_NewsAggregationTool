"""
Authentication utilities — bcrypt password hashing + JWT tokens.
"""
import os, sqlite3, bcrypt, jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Request
from config import config

JWT_SECRET = os.environ.get('JWT_SECRET', 'news-web-dev-secret-change-in-production')
JWT_ALGORITHM = 'HS256'
TOKEN_EXPIRE_HOURS = 720  # 内网工具，30 天有效期


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_token(user_id: int, username: str, role: str) -> str:
    """Generate a JWT token for the user."""
    payload = {
        'sub': str(user_id),              # PyJWT 2.13+ 要求 sub 为字符串
        'username': username,
        'role': role,
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_by_id(db_path: str, user_id: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id, username, display_name, role, created_at, last_login FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id': row[0], 'username': row[1], 'display_name': row[2],
        'role': row[3], 'created_at': row[4], 'last_login': row[5],
    }


def get_current_user(request: Request) -> dict:
    """FastAPI dependency — extracts and validates the JWT from Authorization header.
    Raises 401 if missing or invalid."""
    if not config.db_path:
        raise HTTPException(503, "database_not_configured")

    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        raise HTTPException(401, "missing_token")

    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "invalid_or_expired_token")

    user = get_user_by_id(config.db_path, int(payload['sub']))
    if not user:
        raise HTTPException(401, "user_not_found")

    return user


def optional_user(request: Request) -> dict | None:
    """FastAPI dependency — extracts user if token present, but doesn't require it."""
    if not config.db_path:
        return None
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    payload = decode_token(token)
    if not payload:
        return None
    return get_user_by_id(config.db_path, payload['sub'])
