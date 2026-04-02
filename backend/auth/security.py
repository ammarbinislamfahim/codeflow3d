# backend/auth/security.py - PASSWORD & API KEY HASHING

import bcrypt
import hashlib
import secrets
import os
from datetime import datetime, timedelta
import jwt
from typing import Optional

_BCRYPT_ROUNDS = 12

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY", "")
_KNOWN_INSECURE_SECRETS = {
    "",
    "change-in-production-min-32-chars",
    "codeflow3d-dev-secret-key-min32chars!!",
    "dev-jwt-secret-min-32-chars-replace-in-prod",
}
if JWT_SECRET in _KNOWN_INSECURE_SECRETS:
    import warnings
    JWT_SECRET = JWT_SECRET or "dev-only-insecure-jwt-secret-replace-me"
    warnings.warn(
        "JWT_SECRET is not set or is a known default value. "
        "Set a strong JWT_SECRET environment variable in production!",
        stacklevel=2,
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def generate_api_key() -> str:
    """Generate a new API key with cf_live_ prefix"""
    random_part = secrets.token_urlsafe(40)
    return f"cf_live_{random_part}"


def hash_api_key(key: str) -> str:
    """Hash API key for storage - NEVER store plaintext"""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_api_key(provided_key: str, stored_hash: str) -> bool:
    """Verify provided key against hash using timing-safe comparison"""
    try:
        provided_hash = hash_api_key(provided_key)
        return secrets.compare_digest(provided_hash, stored_hash)
    except Exception:
        return False


def create_access_token(
    user_id: int,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT access token for user"""
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    expire = datetime.utcnow() + expires_delta

    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow()
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def verify_token(token: str) -> Optional[int]:
    """Verify JWT token and return user_id"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return int(user_id)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError, TypeError):
        return None
