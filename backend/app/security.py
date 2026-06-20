"""Security utilities: rate limiting, login lockout, input sanitization."""

import time
import re
import html
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

# ── Rate Limiting (in-memory, production use Redis) ──
_rate_limit_store: dict = {}  # ip -> [(timestamp, count)]

async def rate_limit(request: Request, limit: int = None, window: int = None):
    """Simple sliding-window rate limiter."""
    limit = limit or settings.RATE_LIMIT_REQUESTS
    window = window or settings.RATE_LIMIT_WINDOW
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries
    if client_ip in _rate_limit_store:
        _rate_limit_store[client_ip] = [
            ts for ts in _rate_limit_store[client_ip] if now - ts < window
        ]
    else:
        _rate_limit_store[client_ip] = []

    if len(_rate_limit_store[client_ip]) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

    _rate_limit_store[client_ip].append(now)


# ── Login Lockout ──
_login_attempts: dict = {}  # username -> {"count": int, "locked_until": float}

def check_login_lockout(username: str) -> Optional[float]:
    """Return remaining lockout seconds if locked, else None."""
    record = _login_attempts.get(username)
    if not record:
        return None
    locked_until = record.get("locked_until", 0)
    if locked_until and time.time() < locked_until:
        return locked_until - time.time()
    # Reset if lockout expired
    if locked_until and time.time() >= locked_until:
        _login_attempts[username] = {"count": 0, "locked_until": 0}
    return None

def record_login_failure(username: str):
    """Record a failed login attempt."""
    if username not in _login_attempts:
        _login_attempts[username] = {"count": 0, "locked_until": 0}
    _login_attempts[username]["count"] += 1
    if _login_attempts[username]["count"] >= settings.MAX_LOGIN_ATTEMPTS:
        _login_attempts[username]["locked_until"] = time.time() + settings.LOGIN_LOCKOUT_MINUTES * 60

def record_login_success(username: str):
    """Clear failed attempts on successful login."""
    _login_attempts.pop(username, None)


# ── Input Validation ──
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{3,50}$")

def validate_username(username: str) -> bool:
    return bool(_USERNAME_PATTERN.match(username))

def validate_password(password: str) -> tuple[bool, str]:
    """Return (is_valid, error_message)."""
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters"
    # Require at least one letter and one number
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return False, "Password must contain at least one letter and one number"
    return True, ""

def sanitize_text(text: str, max_length: int = 10000) -> str:
    """Sanitize user input: strip, escape HTML, limit length."""
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    text = html.escape(text)
    if len(text) > max_length:
        text = text[:max_length]
    return text

def sanitize_command_arg(arg: str) -> str:
    """Escape shell command arguments to prevent injection."""
    # Remove dangerous characters
    arg = re.sub(r'[;&|`$(){}[\]\\\n\r<>]', '', arg)
    return arg.strip()


# ── JWT Auth Dependency ──
security_bearer = HTTPBearer(auto_error=False)

async def get_current_user_token(credentials: HTTPAuthorizationCredentials = None):
    """Extract and return token from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
