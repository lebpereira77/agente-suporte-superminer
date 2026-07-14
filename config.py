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

    # WhatsApp Cloud API oficial — usado pelo servidor MCP (mcp_server.py)
    meta_access_token: str = Field(default="", env="META_ACCESS_TOKEN")
    meta_phone_number_id: str = Field(default="", env="META_PHONE_NUMBER_ID")
    meta_waba_id: str = Field(default="", env="META_WABA_ID")
    meta_graph_api_version: str = Field(default="v20.0", env="META_GRAPH_API_VERSION")

    # Segmento secreto da URL do servidor MCP — funciona como chave de acesso
    # (ex: https://.../mcp/<mcp_secret_path>). Gere algo longo e aleatório.
    mcp_secret_path: str = Field(default="", env="MCP_SECRET_PATH")

    class Config:
        env_file = ".env"


settings = Settings()
