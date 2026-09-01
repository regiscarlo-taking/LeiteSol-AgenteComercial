from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from pydantic import BaseModel

from leitesol_api.infrastructure.settings import get_settings

# Context para hashing de passwords
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme - integra automaticamente com o Swagger
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    username: str
    token_type: str = "access"  # "access" ou "refresh"


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Cria um JWT access token."""
    settings = get_settings()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiration_hours)

    to_encode = {
        "sub": username,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def create_refresh_token(username: str) -> str:
    """Cria um JWT refresh token."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_refresh_expiration_hours)

    to_encode = {
        "sub": username,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def verify_token(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Valida e extrai dados do JWT token."""
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
        username: str = payload.get("sub")
        token_type: str = payload.get("type", "access")
        
        if username is None:
            raise credentials_exception
        
        # Rejeitar refresh tokens em endpoints que esperam access tokens
        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token required",
            )
        
        return TokenData(username=username, token_type=token_type)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise credentials_exception


def authenticate_user(username: str, password: str) -> bool:
    """Autentica o usuário contra as credenciais configuradas."""
    settings = get_settings()
    
    if not settings.basic_auth_username or not settings.basic_auth_password:
        return False
    
    if username != settings.basic_auth_username:
        return False
    
    # Usar timing-safe comparison com bcrypt
    return pwd_context.verify(password, settings.basic_auth_password)
