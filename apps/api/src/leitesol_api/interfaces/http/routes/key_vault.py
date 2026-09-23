import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from leitesol_api.infrastructure.auth import verify_token
from leitesol_api.infrastructure.azure_storage import (
    AzureConfigurationError,
    get_key_vault_secret_provider,
)
from leitesol_api.infrastructure.settings import get_settings

router = APIRouter(
    prefix="/azure/key-vault",
    tags=["azure-key-vault"],
    dependencies=[Depends(verify_token)],
)
logger = logging.getLogger("leitesol.api.azure.key_vault")


@router.get("/secrets/{secret_name}")
def get_secret(secret_name: str, request: Request) -> dict[str, object]:
    """Busca um secret individual para validar o acesso ao Key Vault.

    Esta rota é temporária para validação operacional e exige Bearer token.
    O valor nunca é escrito nos logs.
    """
    if not secret_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret name is required.",
        )

    try:
        settings = get_settings()
        value = get_key_vault_secret_provider().get_secret(secret_name)
    except AzureConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception(
            "Key Vault secret lookup failed secret_name=%s vault_configured=%s",
            secret_name,
            bool(get_settings().key_vault_url),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to read the requested Key Vault secret.",
        ) from error

    return {
        "secret_name": secret_name,
        "value": value,
        "trace_id": getattr(request.state, "request_id", None),
    }