from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite+aiosqlite:///suporte.db",
        env="DATABASE_URL",
    )
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")

    # Z-API
    zapi_instance_id: str = Field(default="", env="ZAPI_INSTANCE_ID")
    zapi_token: str = Field(default="", env="ZAPI_TOKEN")
    # Security token opcional — Z-API envia no header Client-Token para validar origem do webhook
    zapi_security_token: str = Field(default="", env="ZAPI_SECURITY_TOKEN")
    zapi_base_url: str = Field(default="https://api.z-api.io", env="ZAPI_BASE_URL")

    # Número de Eduardo para escalação (E.164 sem +)
    suporte_eduardo_phone: str = Field(default="5512981116444", env="SUPORTE_EDUARDO_PHONE")

    # Webhook oficial (Cloud API) — opt-out da campanha de disparo
    meta_verify_token: str = Field(default="", env="META_VERIFY_TOKEN")
    meta_optout_secret: str = Field(default="", env="META_OPTOUT_SECRET")

    class Config:
        env_file = ".env"


settings = Settings()
