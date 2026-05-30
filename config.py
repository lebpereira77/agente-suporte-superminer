from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite+aiosqlite:///suporte.db",
        env="DATABASE_URL",
    )
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")

    # Evolution API
    evolution_api_url: str = Field(default="", env="EVOLUTION_API_URL")
    evolution_api_key: str = Field(default="", env="EVOLUTION_API_KEY")
    evolution_instance: str = Field(default="superminer", env="EVOLUTION_INSTANCE")

    # Número de Eduardo para escalação (E.164 sem +)
    suporte_eduardo_phone: str = Field(default="5512981116444", env="SUPORTE_EDUARDO_PHONE")

    class Config:
        env_file = ".env"


settings = Settings()
