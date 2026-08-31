from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "leitesol-api"
    api_version: str = "v1"
    environment: Literal["development", "staging", "production"] = "development"
    allowed_origins: str = "http://localhost:3000,http://localhost:3001"
    allowed_hosts: str = "localhost,127.0.0.1,api,testserver"
    api_key: str = ""
    fabric_powerbi_url: str = ""
    fabric_workspace_id: str = ""
    fabric_warehouse_id: str = ""
    fabric_server: str = ""
    fabric_database: str = "AgenteFaturamentoDW"
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    fabric_driver: str = "ODBC Driver 18 for SQL Server"
    fabric_connection_timeout: int = 10

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LEITESOL_API_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
