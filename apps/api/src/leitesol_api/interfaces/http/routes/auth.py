from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from leitesol_api.infrastructure.auth import (
    LoginRequest,
    Token,
    TokenData,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    verify_token,
    oauth2_scheme,
)
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.schemas import RefreshTokenRequest

router = APIRouter(tags=["authentication"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/token", response_model=Token)
@limiter.limit("5/minute")
async def login(request: Request, credentials: LoginRequest) -> Token:
    """
    Autentica e retorna tokens JWT (access + refresh).
    
    **Limite**: 5 requisições por minuto por IP.
    
    **Credenciais em desenvolvimento**:
    - username: admin
    - password: (conforme LEITESOL_API_BASIC_AUTH_PASSWORD no .env)
    """
    settings = get_settings()
    if settings.effective_auth_mode != "local":
        # Fora de development o login é do Entra ID; esta rota não existe.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    if not authenticate_user(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Gerar tokens
    access_token = create_access_token(credentials.username)
    refresh_token = create_refresh_token(credentials.username)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_expiration_hours * 3600,
    )


@router.post("/token/refresh", response_model=Token)
async def refresh_access_token(body: RefreshTokenRequest) -> Token:
    """
    Renovar access token usando refresh token.
    
    Não requer re-autenticação. O refresh token vai no corpo, nunca na URL,
    para não ficar registrado em log de proxy.
    """
    settings = get_settings()
    if settings.effective_auth_mode != "local":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    refresh_token = body.refresh_token
    
    try:
        import jwt
        payload = jwt.decode(
            refresh_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        username = payload.get("sub")
        token_type = payload.get("type")
        
        if not isinstance(username, str) or token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token required",
            )
        
        # Gerar novo access token
        access_token = create_access_token(username)
        new_refresh_token = create_refresh_token(username)
        
        return Token(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_expiration_hours * 3600,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
