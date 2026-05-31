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
    event = payload.get("event") or event_hint or ""
    if event.upper().replace(".", "_").replace("-", "_") != "MESSAGES_UPSERT":
        return {"status": "ignored"}

    data = payload.get("data", {})
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
    push_name: str | None = data.get("pushName")
    print(f"[MSG] de={phone} jid={remote_jid} pushName={push_name!r} texto={texto[:40]!r}")

    # Recupera ou cria conversa, atualizando remote_jid e push_name
    result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == phone))
    conversa = result.scalar_one_or_none()

    if conversa is None:
        conversa = SuporteConversa(phone=phone, remote_jid=remote_jid, nome_usuario=push_name)
        db.add(conversa)
    else:
        if conversa.remote_jid != remote_jid:
            conversa.remote_jid = remote_jid
        if push_name and not conversa.nome_usuario:
            conversa.nome_usuario = push_name

    # reply_to usa o JID original (inclui @lid quando necessário)
    reply_to = remote_jid

    if phone == _EDUARDO:
        if await _processar_admin(phone, reply_to, push_name, texto, db):
            return {"status": "ok", "admin": True}

    if conversa.modo_humano:
        nome = conversa.nome_usuario or phone
        await enviar_mensagem(_EDUARDO, f"💬 {nome} ({phone}):\n{texto}", push_name=None)
        return {"status": "ok", "forwarded": True}

    try:
        resposta = await suporte_agent.processar_mensagem(phone, texto, db)
        await enviar_mensagem(reply_to, resposta, push_name=push_name)
    except Exception as e:
        print(f"[ERROR] {e}")
        await enviar_mensagem(reply_to, "Desculpe, tive um problema técnico. Tente novamente.", push_name=push_name)

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
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}
    return await _handle(payload, event_path, db)


async def _processar_admin(
    phone: str, reply_to: str, push_name: str | None, texto: str, db: AsyncSession
) -> bool:
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
        await enviar_mensagem(reply_to, msg, push_name=push_name)
        return True

    if cmd.startswith("!retomar "):
        target = cmd.removeprefix("!retomar ").strip()
        result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == target))
        conversa = result.scalar_one_or_none()
        if not conversa:
            await enviar_mensagem(reply_to, f"Conversa {target} não encontrada.", push_name=push_name)
        else:
            conversa.modo_humano = False
            await db.commit()
            await enviar_mensagem(reply_to, f"✅ Bot reativado para {target}.", push_name=push_name)
            target_jid = conversa.remote_jid or target
            await enviar_mensagem(target_jid, "Olá! O suporte automático está de volta. Como posso ajudar?",
                                  push_name=conversa.nome_usuario)
        return True

    return False
