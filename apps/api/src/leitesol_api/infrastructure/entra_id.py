from typing import Protocol


class AccessTokenProvider(Protocol):
    def get_token(self) -> str: ...


class EntraIdClientCredentials:
    def __init__(self, *, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret

    def get_token(self) -> str:
        from azure.identity import ClientSecretCredential

        credential = ClientSecretCredential(
            tenant_id=self._tenant_id,
            client_id=self._client_id,
            client_secret=self._client_secret,
        )
        return credential.get_token("https://database.windows.net/.default").token