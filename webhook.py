"""Webhook da Evolution API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from evolution_service import enviar_mensagem, extrair_phone, is_grupo
from models import SuporteConversa
import suporte_agent

router = APIRouter()

_EDUARDO = settings.suporte_eduardo_phone


def _extrair_texto(data: dict) -> str | None:
    msg = data.get("message", {})
    return (
        msg.get("conversation")
        or msg.get("extendedTextMessage", {}).get("text")
        or None
    )


async def _handle(payload: dict, event_hint: str | None, db: AsyncSession) -> dict:
    """Processa o payload normalizado. event_hint vem do path quando webhook_by_events=true."""
    # Normaliza o evento: body tem prioridade; fallback para path hint
    event = payload.get("event") or event_hint or ""
    # Evolution API usa tanto "messages.upsert" quanto "MESSAGES_UPSERT"
    if event.upper().replace(".", "_").replace("-", "_") != "MESSAGES_UPSERT":
        return {"status": "ignored"}

    data = payload.get("data", {})
    # webhook_by_events=true: data está direto no payload root
    if not data and "key" in payload:
        data = payload

    key = data.get("key", {})
    if key.get("fromMe"):
        return {"status": "ignored"}

    remote_jid = key.get("remoteJid", "")
    if is_grupo(remote_jid):
        return {"status": "ignored"}

    phone = extrair_phone(remote_jid)
    texto = _extrair_texto(data)
    if not texto or not texto.strip():
        return {"status": "ignored"}

    texto = texto.strip()

    if phone == _EDUARDO:
        if await _processar_admin(phone, texto, db):
            return {"status": "ok", "admin": True}

    result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == phone))
    conversa = result.scalar_one_or_none()

    if conversa and conversa.modo_humano:
        await enviar_mensagem(_EDUARDO, f"💬 Mensagem de {phone}:\n{texto}")
        return {"status": "ok", "forwarded": True}

    try:
        resposta = await suporte_agent.processar_mensagem(phone, texto, db)
        await enviar_mensagem(phone, resposta)
    except Exception as e:
        print(f"[ERROR] {e}")
        await enviar_mensagem(phone, "Desculpe, tive um problema técnico. Tente novamente.")

    return {"status": "ok"}


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}
    return await _handle(payload, None, db)


@router.post("/webhook/whatsapp/{event_path:path}")
async def whatsapp_webhook_by_event(
    event_path: str, request: Request, db: AsyncSession = Depends(get_db)
):
    # webhook_by_events=true envia para /webhook/whatsapp/messages-upsert etc.
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}
    return await _handle(payload, event_path, db)


async def _processar_admin(phone: str, texto: str, db: AsyncSession) -> bool:
    cmd = texto.strip().lower()

    if cmd == "!status":
        result = await db.execute(
            select(SuporteConversa).where(SuporteConversa.modo_humano == True)  # noqa: E712
        )
        pausadas = result.scalars().all()
        if not pausadas:
            msg = "Nenhuma conversa em modo humano."
        else:
            linhas = [f"• {c.phone} — {c.nome_usuario or 'sem nome'}" for c in pausadas]
            msg = f"*Conversas pausadas ({len(pausadas)}):*\n" + "\n".join(linhas)
            msg += "\n\nPara retomar: *!retomar <phone>*"
        await enviar_mensagem(phone, msg)
        return True

    if cmd.startswith("!retomar "):
        target = cmd.removeprefix("!retomar ").strip()
        result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == target))
        conversa = result.scalar_one_or_none()
        if not conversa:
            await enviar_mensagem(phone, f"Conversa {target} não encontrada.")
        else:
            conversa.modo_humano = False
            await db.commit()
            await enviar_mensagem(phone, f"✅ Bot reativado para {target}.")
            await enviar_mensagem(target, "Olá! O suporte automático está de volta. Como posso ajudar?")
        return True

    return False
