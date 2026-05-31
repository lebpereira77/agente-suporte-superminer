"""Webhook Z-API — recebe mensagens WhatsApp."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from evolution_service import enviar_mensagem, is_grupo
from models import SuporteConversa
import suporte_agent

router = APIRouter()

_EDUARDO = settings.suporte_eduardo_phone


def _extrair_texto(payload: dict) -> str | None:
    """Extrai texto de mensagens Z-API (text, image caption, document caption)."""
    text_obj = payload.get("text") or {}
    return (
        text_obj.get("message")
        or payload.get("caption")
        or None
    )


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    client_token: str | None = Header(default=None, alias="Client-Token"),
):
    print(f"[WEBHOOK-IN] client_token={client_token!r} configured={bool(settings.zapi_security_token)}")

    # Valida security token se configurado
    if settings.zapi_security_token and client_token != settings.zapi_security_token:
        print(f"[WEBHOOK-IN] token mismatch — ignorando (recebido={client_token!r})")
        return {"status": "unauthorized"}

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    return await _handle(payload, db)


async def _handle(payload: dict, db: AsyncSession) -> dict:
    tipo = payload.get("type", "")
    print(f"[WEBHOOK] type={tipo!r} fromMe={payload.get('fromMe')} phone={payload.get('phone')!r} keys={list(payload.keys())[:8]}")

    if payload.get("fromMe") or tipo not in ("ReceivedCallback",):
        return {"status": "ignored"}

    phone: str = payload.get("phone", "")
    if not phone:
        return {"status": "ignored"}

    # Ignorar grupos e broadcasts
    if is_grupo(phone):
        return {"status": "ignored"}

    texto = _extrair_texto(payload)
    if not texto or not texto.strip():
        return {"status": "ignored"}

    texto = texto.strip()
    push_name: str | None = payload.get("senderName") or payload.get("chatName")

    print(f"[MSG] de={phone} pushName={push_name!r} texto={texto[:40]!r}")

    # Recupera ou cria conversa
    result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == phone))
    conversa = result.scalar_one_or_none()

    if conversa is None:
        conversa = SuporteConversa(phone=phone, remote_jid=phone, nome_usuario=push_name)
        db.add(conversa)
    else:
        if push_name and not conversa.nome_usuario:
            conversa.nome_usuario = push_name

    if phone == _EDUARDO:
        if await _processar_admin(phone, push_name, texto, db):
            return {"status": "ok", "admin": True}

    if conversa.modo_humano:
        nome = conversa.nome_usuario or phone
        await enviar_mensagem(_EDUARDO, f"💬 {nome} ({phone}):\n{texto}")
        return {"status": "ok", "forwarded": True}

    try:
        resposta = await suporte_agent.processar_mensagem(phone, texto, db)
        await enviar_mensagem(phone, resposta)
    except Exception as e:
        print(f"[ERROR] {e}")
        await enviar_mensagem(phone, "Desculpe, tive um problema técnico. Tente novamente.")

    return {"status": "ok"}


async def _processar_admin(
    phone: str, push_name: str | None, texto: str, db: AsyncSession
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
