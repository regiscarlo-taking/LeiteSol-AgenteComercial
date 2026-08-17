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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    model_config = SettingsConfigDict(env_prefix="LEITESOL_API_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
