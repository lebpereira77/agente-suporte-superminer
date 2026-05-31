"""Cliente para a Evolution API (WhatsApp)."""
from __future__ import annotations

import httpx

from config import settings


def _headers() -> dict:
    return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}


async def _buscar_phone_por_pushname(push_name: str) -> str | None:
    """Resolve lid → phone via contacts. Retorna JID @s.whatsapp.net ou None."""
    if not push_name:
        return None
    url = f"{settings.evolution_api_url.rstrip('/')}/chat/findContacts/{settings.evolution_instance}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, headers=_headers(), json={})
            if r.status_code != 200:
                return None
            contacts = r.json()
            if not isinstance(contacts, list):
                return None
            for c in contacts:
                if c.get("pushName") == push_name and "@s.whatsapp.net" in c.get("id", ""):
                    return c["id"].split("@")[0]
    except Exception:
        pass
    return None


async def enviar_mensagem(numero: str, texto: str, push_name: str | None = None) -> bool:
    """Envia mensagem de texto. Retorna True se OK.

    Se `numero` for um lid (não resolve no WhatsApp), tenta fallback via push_name.
    """
    if not settings.evolution_api_url or not settings.evolution_api_key:
        print(f"[WARN] Evolution API não configurada — mensagem para {numero} não enviada")
        return False

    url = f"{settings.evolution_api_url.rstrip('/')}/message/sendText/{settings.evolution_instance}"

    async def _tentar(dest: str) -> bool:
        payload = {"number": dest, "textMessage": {"text": texto}}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, headers=_headers(), json=payload)
                if r.status_code in (200, 201):
                    return True
                # lid não existe no WhatsApp — retornar False para tentar fallback
                if "exists" in r.text and "false" in r.text:
                    return False
                print(f"[ERROR] Evolution API {r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            print(f"[ERROR] Falha ao enviar para {dest}: {e}")
            return False

    if await _tentar(numero):
        return True

    # Lid falhou — tentar resolver pelo pushName
    if push_name:
        phone_fallback = await _buscar_phone_por_pushname(push_name)
        if phone_fallback and phone_fallback != numero:
            print(f"[LID] Fallback {numero} → {phone_fallback} via pushName={push_name!r}")
            return await _tentar(phone_fallback)

    return False


def extrair_phone(remote_jid: str) -> str:
    """'5512988116444@s.whatsapp.net' ou '51230453809244@lid' → parte numérica"""
    return remote_jid.split("@")[0]


def is_grupo(remote_jid: str) -> bool:
    return remote_jid.endswith("@g.us")
