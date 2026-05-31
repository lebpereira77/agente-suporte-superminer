"""Cliente Z-API para envio de mensagens WhatsApp."""
from __future__ import annotations

import httpx

from config import settings


def _base_url() -> str:
    return (
        f"{settings.zapi_base_url.rstrip('/')}"
        f"/instances/{settings.zapi_instance_id}"
        f"/token/{settings.zapi_token}"
    )


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if settings.zapi_security_token:
        h["Client-Token"] = settings.zapi_security_token
    return h


async def enviar_mensagem(phone: str, texto: str, **_kwargs) -> bool:
    """Envia mensagem de texto via Z-API. phone = número E.164 sem + (ex: 5512981116444)."""
    if not settings.zapi_instance_id or not settings.zapi_token:
        print(f"[WARN] Z-API não configurada — mensagem para {phone} não enviada")
        return False

    # phone pode chegar como JID completo (ex: 5512981116444@s.whatsapp.net ou @lid)
    phone = _normalizar_phone(phone)

    url = f"{_base_url()}/send-text"
    payload = {"phone": phone, "message": texto}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=_headers(), json=payload)
            if r.status_code not in (200, 201):
                print(f"[ERROR] Z-API {r.status_code}: {r.text[:200]}")
                return False
        return True
    except Exception as e:
        print(f"[ERROR] Falha ao enviar para {phone}: {e}")
        return False


def _normalizar_phone(phone: str) -> str:
    """Remove sufixo @s.whatsapp.net/@lid e mantém só os dígitos."""
    return phone.split("@")[0]


def extrair_phone(remote_jid: str) -> str:
    """Extrai o número de um JID. Compatível com @s.whatsapp.net e @lid."""
    return remote_jid.split("@")[0]


def is_grupo(remote_jid: str) -> bool:
    return remote_jid.endswith("@g.us") or remote_jid.endswith("@broadcast")
