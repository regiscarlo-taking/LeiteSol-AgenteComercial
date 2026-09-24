from collections.abc import Iterator
from functools import lru_cache
from typing import TYPE_CHECKING, BinaryIO

from azure.core.credentials import TokenCredential
from azure.identity import ChainedTokenCredential, ClientSecretCredential, DefaultAzureCredential

if TYPE_CHECKING:
    from azure.storage.blob import BlobClient

from leitesol_api.infrastructure.settings import Settings, get_settings


class AzureConfigurationError(RuntimeError):
    """Raised when an Azure resource is not configured."""


class KeyVaultSecretProvider:
    def __init__(self, *, vault_url: str, credential: TokenCredential) -> None:
        if not vault_url:
            raise AzureConfigurationError("LEITESOL_API_KEY_VAULT_URL is not configured.")
        from azure.keyvault.secrets import SecretClient

        self._client = SecretClient(vault_url=vault_url, credential=credential)

    def get_secret(self, name: str) -> str:
        if not name:
            raise AzureConfigurationError("The Key Vault secret name is empty.")
        return self._client.get_secret(name).value

    def get_gemini_api_key(self, settings: Settings) -> str:
        return self.get_secret(settings.gemini_api_key_secret_name)


class BlobStorageGateway:
    def __init__(
        self,
        *,
        account_url: str,
        container_name: str,
        credential: TokenCredential,
        blob_prefix: str = "",
    ) -> None:
        if not account_url:
            raise AzureConfigurationError(
                "LEITESOL_API_STORAGE_ACCOUNT_URL is not configured."
            )
        if not container_name:
            raise AzureConfigurationError(
                "LEITESOL_API_STORAGE_CONTAINER_NAME is not configured."
            )

        from azure.storage.blob import BlobServiceClient

        self._container = BlobServiceClient(
            account_url=account_url,
            credential=credential,
        ).get_container_client(container_name)
        self._blob_prefix = blob_prefix.strip("/")

    def _blob_name(self, name: str) -> str:
        normalized_name = name.strip("/")
        if not normalized_name:
            raise ValueError("The blob name cannot be empty.")
        if self._blob_prefix:
            return f"{self._blob_prefix}/{normalized_name}"
        return normalized_name

    def upload(self, name: str, content: BinaryIO | bytes, *, overwrite: bool = False) -> str:
        blob_name = self._blob_name(name)
        self._container.upload_blob(name=blob_name, data=content, overwrite=overwrite)
        return blob_name

    def download(self, name: str) -> bytes:
        return self._container.download_blob(self._blob_name(name)).readall()

    def delete(self, name: str) -> None:
        self._container.delete_blob(self._blob_name(name))

    def list_names(self, prefix: str = "") -> Iterator[str]:
        effective_prefix = self._blob_name(prefix) if prefix else self._blob_prefix
        for blob in self._container.list_blobs(name_starts_with=effective_prefix):
            yield blob.name

    def get_blob_client(self, name: str) -> "BlobClient":
        return self._container.get_blob_client(self._blob_name(name))


@lru_cache(maxsize=1)
def get_azure_credential() -> TokenCredential:
    """Use the configured service principal and fall back to Azure credentials.

    The explicit credential is first because an expired Azure CLI session makes
    DefaultAzureCredential stop its own chain. Managed Identity remains the
    fallback for deployments without LEITESOL_API_ENTRA_* values.
    """
    settings = get_settings()
    default_credential = DefaultAzureCredential()
    if not all((settings.entra_tenant_id, settings.entra_client_id, settings.entra_client_secret)):
        return default_credential

    service_principal_credential = ClientSecretCredential(
        tenant_id=settings.entra_tenant_id,
        client_id=settings.entra_client_id,
        client_secret=settings.entra_client_secret.replace("$$", "$"),
    )
    return ChainedTokenCredential(service_principal_credential, default_credential)


@lru_cache(maxsize=1)
def get_key_vault_secret_provider() -> KeyVaultSecretProvider:
    settings = get_settings()
    return KeyVaultSecretProvider(
        vault_url=settings.key_vault_url,
        credential=get_azure_credential(),
    )


@lru_cache(maxsize=1)
def get_blob_storage_gateway() -> BlobStorageGateway:
    settings = get_settings()
    return BlobStorageGateway(
        account_url=settings.storage_account_url,
        container_name=settings.storage_container_name,
        credential=get_azure_credential(),
        blob_prefix=settings.storage_blob_prefix,
    )


def get_blob_client(name: str) -> "BlobClient":
    return get_blob_storage_gateway().get_blob_client(name)
