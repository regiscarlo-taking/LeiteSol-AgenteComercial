from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from leitesol_api.infrastructure.settings import get_settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    username: str
    token_type: str = "access"


def create_access_token(
    username: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    settings = get_settings()

    expire = (
        datetime.now(timezone.utc) + expires_delta
        if expires_delta
        else datetime.now(timezone.utc)
        + timedelta(hours=settings.jwt_expiration_hours)
    )

    payload = {
        "sub": username,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(username: str) -> str:
    settings = get_settings()

    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.jwt_refresh_expiration_hours
    )

    payload = {
        "sub": username,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_token(
    token: str = Depends(oauth2_scheme),
) -> TokenData:
    settings = get_settings()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        username = payload.get("sub")
        token_type = payload.get("type")

        if not isinstance(username, str):
            raise credentials_exception

        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return TokenData(
            username=username,
            token_type="access",
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except jwt.InvalidTokenError:
        raise credentials_exception


def authenticate_user(
    username: str,
    password: str,
) -> bool:
    settings = get_settings()

    if not settings.basic_auth_username:
        return False

    if not settings.basic_auth_password:
        return False

    if username != settings.basic_auth_username:
        return False

    password_hash = settings.basic_auth_password.replace("$$", "$")

    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False