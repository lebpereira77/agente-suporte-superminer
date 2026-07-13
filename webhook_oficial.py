"""Webhook WhatsApp Cloud API (oficial da Meta) — só opt-out da campanha de disparo.

Não responde nada ao usuário (isso é papel do Chatwoot/atendimento humano quando existir).
Só escuta: clique em botão de template que não seja a opção positiva, ou texto contendo
"parar/sair/cancelar/remover/stop", e grava o número em WhatsappOptout — consultada pelo
script execution/disparar_whatsapp_oficial.py antes de cada disparo.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import WhatsappOptout

router = APIRouter()

_BOTOES_POSITIVOS = {"sim, por favor!", "sim"}
_RE_OPTOUT_TEXTO = re.compile(r"\b(parar|sair|cancelar|remover|stop)\b", re.IGNORECASE)


@router.get("/webhook/whatsapp-oficial")
async def verificar_webhook(request: Request):
    """Handshake de verificação exigido pela Meta ao registrar o webhook."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and settings.meta_verify_token
        and params.get("hub.verify_token") == settings.meta_verify_token
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Token inválido", status_code=403)


@router.post("/webhook/whatsapp-oficial")
async def whatsapp_oficial_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                await _processar_mensagem(msg, db)

    return {"status": "ok"}


async def _processar_mensagem(msg: dict, db: AsyncSession) -> None:
    numero = msg.get("from", "")
    if not numero:
        return

    tipo = msg.get("type")
    motivo: str | None = None

    if tipo == "button":
        texto_botao = (msg.get("button") or {}).get("text", "").strip()
        if texto_botao and texto_botao.lower() not in _BOTOES_POSITIVOS:
            motivo = f"botão: {texto_botao}"
    elif tipo == "text":
        texto = (msg.get("text") or {}).get("body", "")
        if texto and _RE_OPTOUT_TEXTO.search(texto):
            motivo = f"texto: {texto[:100]}"

    if not motivo:
        return

    existente = await db.execute(select(WhatsappOptout).where(WhatsappOptout.numero == numero))
    if existente.scalar_one_or_none():
        return

    db.add(WhatsappOptout(numero=numero, motivo=motivo))
    await db.commit()
    print(f"[OPTOUT] {numero} — {motivo}")


@router.get("/webhook/whatsapp-oficial/lista")
async def listar_optout(request: Request, db: AsyncSession = Depends(get_db)):
    """Lista de opt-out em JSON — consumida por execution/disparar_whatsapp_oficial.py."""
    secret = request.headers.get("X-Optout-Secret", "")
    if not settings.meta_optout_secret or secret != settings.meta_optout_secret:
        raise HTTPException(status_code=403, detail="Acesso restrito")

    resultado = await db.execute(select(WhatsappOptout))
    return [
        {"numero": r.numero, "motivo": r.motivo, "criado_em": r.criado_em.isoformat()}
        for r in resultado.scalars().all()
    ]
