import hashlib
import hmac
import os
import re
import secrets
import time

from apps.api.db import connect


SESSION_COOKIE = "computer_sales_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
_PASSWORD_ITERATIONS = 310_000
_DUMMY_SALT = b"computer-sales-dummy"
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"not-a-real-password", _DUMMY_SALT, _PASSWORD_ITERATIONS
)
_sessions: dict[str, dict] = {}


def _configured_credentials() -> tuple[str, str]:
    username = os.environ.get("ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    if not username or not password:
        raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD must not be empty")
    if os.environ.get("APP_ENV") == "production":
        if password == "ChangeMe123!" or len(password) < 14:
            raise RuntimeError(
                "Production requires a non-default ADMIN_PASSWORD "
                "of at least 14 characters"
            )
    return username, password


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)


def ensure_admin_account() -> None:
    username, password = _configured_credentials()
    with connect() as connection:
        row = connection.execute(
            "SELECT role FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if row:
            if row["role"] != "admin":
                raise RuntimeError(
                    "Configured ADMIN_USERNAME is already assigned to a non-admin account"
                )
            return
        salt = secrets.token_bytes(16)
        connection.execute(
            "INSERT INTO users (username, password_salt, password_hash, role) "
            "VALUES (?, ?, ?, 'admin')",
            (username, salt, _password_hash(password, salt)),
        )


def verify_credentials(username: str, password: str) -> dict | None:
    with connect() as connection:
        user = connection.execute(
            "SELECT username, password_salt, password_hash, role "
            "FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    salt = bytes(user["password_salt"]) if user else _DUMMY_SALT
    expected_hash = bytes(user["password_hash"]) if user else _DUMMY_HASH
    submitted_hash = _password_hash(password, salt)
    if not hmac.compare_digest(submitted_hash, expected_hash) or user is None:
        return None
    return {"username": user["username"], "role": user["role"]}


def create_account(username: str, password: str) -> dict:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise ValueError("Username must be 3-40 letters, numbers, dots, dashes, or underscores.")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters.")
    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO users (username, password_salt, password_hash, role) "
            "VALUES (?, ?, ?, 'staff')",
            (username, salt, password_hash),
        )
        return {
            "id": cursor.lastrowid,
            "username": username,
            "role": "staff",
        }


def list_accounts() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def create_session(username: str, role: str) -> str:
    now = time.time()
    expired = [token for token, session in _sessions.items() if session["expires_at"] <= now]
    for token in expired:
        del _sessions[token]
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "role": role,
        "expires_at": now + SESSION_TTL_SECONDS,
    }
    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    session = _sessions.get(token)
    if session is None:
        return None
    if session["expires_at"] <= time.time():
        del _sessions[token]
        return None
    return {"username": session["username"], "role": session["role"]}


def is_valid_session(token: str | None) -> bool:
    return get_session(token) is not None


def revoke_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def clear_sessions() -> None:
    _sessions.clear()
