from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from leitesol_api.infrastructure.auth import (
    Token,
    authenticate_user,
    create_access_token,
)
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.responses import build_response_payload

router = APIRouter(tags=["authentication"])


@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    """
    Endpoint de autenticação OAuth2.

    Credenciais padrão em desenvolvimento:
    - username: admin
    - password: (conforme LEITESOL_API_BASIC_AUTH_PASSWORD)

    Retorna um JWT access token para usar nos endpoints protegidos.
    """
    settings = get_settings()

    if not authenticate_user(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(hours=settings.jwt_expiration_hours)
    access_token = create_access_token(
        data={"sub": form_data.username},
        expires_delta=access_token_expires,
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_expiration_hours * 3600,
    )
