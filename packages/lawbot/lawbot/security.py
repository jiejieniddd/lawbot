from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from lawbot.domain.schemas import TokenPayload, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"

TOKEN_TYP_ACCESS = "access"
TOKEN_TYP_REFRESH = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    *,
    subject: str,
    email: str,
    role: UserRole | str,
    secret_key: str,
    expires_minutes: int = 15,
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "role": str(role),
        "typ": TOKEN_TYP_ACCESS,
        "exp": expire,
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def create_refresh_token(
    *,
    subject: str,
    email: str,
    role: UserRole | str,
    jti: str,
    secret_key: str,
    expires_days: int = 14,
) -> str:
    expire = datetime.now(UTC) + timedelta(days=expires_days)
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "role": str(role),
        "typ": TOKEN_TYP_REFRESH,
        "jti": jti,
        "exp": expire,
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_token(token: str, secret_key: str) -> TokenPayload:
    try:
        data = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        return TokenPayload(
            sub=data["sub"],
            email=data["email"],
            role=UserRole(data["role"]),
            typ=data["typ"],
            jti=data.get("jti"),
        )
    except (JWTError, KeyError, ValueError) as exc:
        raise ValueError("invalid token") from exc


def decode_access_token(token: str, secret_key: str) -> TokenPayload:
    payload = decode_token(token, secret_key)
    if payload.typ != TOKEN_TYP_ACCESS:
        raise ValueError("invalid token")
    return payload
