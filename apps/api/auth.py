import hashlib
import hmac
import os
import secrets
import time


SESSION_COOKIE = "computer_sales_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
_PASSWORD_ITERATIONS = 310_000
_sessions: dict[str, tuple[float, str, str]] = {}


def _configured_credentials() -> tuple[str, bytes, bytes]:
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    salt = os.environ.get("PASSWORD_SALT")
    if not username or not password:
        raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD must not be empty")
    if os.environ.get("APP_ENV") == "production":
        if password == "ChangeMe123!" or len(password) < 14:
            raise RuntimeError(
                "Production requires a non-default ADMIN_PASSWORD "
                "of at least 14 characters"
            )
        if not salt:
            raise RuntimeError("Production requires a persistent PASSWORD_SALT")
    salt_bytes = salt.encode("utf-8") if salt else b"computer-sales-local-v1"
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, _PASSWORD_ITERATIONS
    )
    return username, salt_bytes, password_hash


def verify_credentials(username: str, password: str) -> bool:
    expected_user, salt, expected_hash = _configured_credentials()
    submitted_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
        submitted_hash, expected_hash
    )


def create_session(username: str = "admin", role: str = "admin") -> str:
    now = time.time()
    expired = [token for token, session in _sessions.items() if session[0] <= now]
    for token in expired:
        del _sessions[token]
    token = secrets.token_urlsafe(32)
    _sessions[token] = (now + SESSION_TTL_SECONDS, username, role)
    return token


def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    session = _sessions.get(token)
    if session is None:
        return False
    if session[0] <= time.time():
        del _sessions[token]
        return False
    return True


def session_identity(token: str | None) -> tuple[str, str] | None:
    if not is_valid_session(token):
        return None
    session = _sessions.get(token)
    return (session[1], session[2]) if session else None


def revoke_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def clear_sessions() -> None:
    _sessions.clear()
