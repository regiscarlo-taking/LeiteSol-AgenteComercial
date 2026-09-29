from datetime import datetime, timedelta, timezone
from functools import lru_cache
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
    # Identidade que decide a alçada: e-mail (tabela de acesso) ou grupo do
    # Entra ID com visão completa (diretoria / Adm. Vendas).
    email: Optional[str] = None
    full_access: bool = False


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


@lru_cache(maxsize=4)
def _entra_jwks_client(tenant_id: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
        cache_keys=True,
    )


def verify_entra_token(token: str) -> TokenData:
    """Valida o access token v2 do Entra ID emitido para esta API.

    Exige assinatura RS256 da chave publicada pelo tenant, `aud` = a API e
    `iss` = o tenant da Leitesol. O registro da aplicação precisa emitir token
    v2 e o claim `groups` para a visão completa.
    """
    settings = get_settings()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        signing_key = _entra_jwks_client(settings.entra_tenant_id).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.entra_api_audience or settings.entra_client_id,
            issuer=f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
        )
    except jwt.PyJWTError:
        raise credentials_exception

    email = payload.get("preferred_username") or payload.get("email") or payload.get("upn")
    if not isinstance(email, str) or not email.strip():
        raise credentials_exception

    groups = payload.get("groups") or []
    return TokenData(
        username=str(payload.get("oid") or email),
        email=email.strip().lower(),
        full_access=bool(settings.full_access_groups & {str(group) for group in groups}),
    )


def verify_token(
    token: str = Depends(oauth2_scheme),
) -> TokenData:
    settings = get_settings()

    if settings.effective_auth_mode == "entra":
        return verify_entra_token(token)

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

        # Login local (development): a alçada vem da configuração, para testar
        # tanto a visão completa quanto a carteira de um e-mail específico.
        return TokenData(
            username=username,
            token_type="access",
            email=settings.local_user_email.strip().lower() or None,
            full_access=settings.local_user_full_access,
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