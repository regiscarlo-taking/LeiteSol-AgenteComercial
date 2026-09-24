from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "leitesol-api"
    api_version: str = "v1"
    environment: Literal["development", "staging", "production"] = "development"
    allowed_origins: str = "http://localhost:3000,http://localhost:3001"
    allowed_hosts: str = "localhost,127.0.0.1,api,testserver"
    api_key: str = ""
    basic_auth_username: str = "admin"
    basic_auth_password: str = ""
    fabric_powerbi_url: str = ""
    fabric_workspace_id: str = ""
    fabric_warehouse_id: str = ""
    fabric_server: str = ""
    fabric_database: str = "AgenteFaturamentoDW"
    fabric_authentication: str = "ActiveDirectoryServicePrincipal"
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    key_vault_url: str = ""
    gemini_api_key_secret_name: str = "GEMINI-API-KEY"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    storage_account_url: str = ""
    storage_container_name: str = ""
    storage_blob_prefix: str = ""
    fabric_driver: str = "ODBC Driver 18 for SQL Server"
    fabric_connection_timeout: int = 10
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    jwt_refresh_expiration_hours: int = 168  # 7 dias

    def __init__(self, **data):
        super().__init__(**data)
        if self.environment == "production" and not self.jwt_secret_key:
            raise ValueError("jwt_secret_key must be set in production environment")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def csp_policy(self) -> str:
        """Content-Security-Policy adaptativa por environment.
        
        A interface Swagger/ReDoc é permitida em todos os ambientes,
        mas com diferentes níveis de restrição para APIs.
        """
        if self.environment == "production":
            return (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
                "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self' https:; "
                "frame-ancestors 'self';"
            )
        # development e staging: mais permissivo para suportar Swagger UI, hot reload e dev tools
        return (
            "default-src 'self' https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https: ws: wss:; "
            "frame-ancestors 'self';"
        )

    model_config = SettingsConfigDict(
        env_file=(Path.cwd() / ".env", Path(__file__).resolve().parents[5] / ".env"),
        env_prefix="LEITESOL_API_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
