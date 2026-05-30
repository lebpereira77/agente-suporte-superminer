"""Cliente para a Evolution API (WhatsApp)."""
from __future__ import annotations

import httpx

from config import settings


def _headers() -> dict:
    return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}


async def enviar_mensagem(numero: str, texto: str) -> bool:
    """Envia mensagem de texto. Retorna True se OK."""
    if not settings.evolution_api_url or not settings.evolution_api_key:
        print(f"[WARN] Evolution API não configurada — mensagem para {numero} não enviada")
        return False

    url = f"{settings.evolution_api_url.rstrip('/')}/message/sendText/{settings.evolution_instance}"
    # Evolution API v1: textMessage wrapper; v2 uses just "text"
    payload = {"number": numero, "textMessage": {"text": texto}}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=_headers(), json=payload)
            if r.status_code not in (200, 201):
                print(f"[ERROR] Evolution API {r.status_code}: {r.text[:200]}")
                return False
        return True
    except Exception as e:
        print(f"[ERROR] Falha ao enviar para {numero}: {e}")
        return False


def extrair_phone(remote_jid: str) -> str:
    """'5512988116444@s.whatsapp.net' → '5512988116444'"""
    return remote_jid.split("@")[0]


def is_grupo(remote_jid: str) -> bool:
    return remote_jid.endswith("@g.us")
