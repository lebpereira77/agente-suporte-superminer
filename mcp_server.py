"""Servidor MCP — WhatsApp oficial (Cloud API) para uso via Connector no claude.ai.

Reaproveita o token/WABA/número já configurados para o disparo em lote
(execution/disparar_whatsapp_oficial.py, no repo minerador-amazon). Este servidor é o que
permite ao agente no app do Claude executar ações de verdade (enviar mensagem, checar
métricas, gerenciar opt-out) em vez de só explicar o que fazer.

Autenticação: sem OAuth — o segredo fica embutido no próprio caminho da URL
(MCP_SECRET_PATH, montado em main.py). Trate essa URL como uma senha.
"""
from __future__ import annotations

import asyncio
import random
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models import MensagemOficialEnviada, WhatsappOptout

FUSO = ZoneInfo("America/Sao_Paulo")

mcp = FastMCP(
    name="whatsapp-oficial-super-miner",
    instructions=(
        "Ferramentas para gerenciar a conta WhatsApp Business oficial (Cloud API) do Super "
        "Miner. Regras obrigatórias: (1) antes de qualquer campanha para uma lista, chame "
        "checar_qualidade_numero — se não for GREEN, avise o usuário e peça confirmação "
        "explícita antes de continuar; (2) nunca tente contornar o opt-out — as ferramentas de "
        "envio já bloqueiam sozinhas, não peça pra usuário forçar; (3) para listas, comece "
        "sempre com um lote pequeno (ex: 20) via `limite`, não a lista inteira de uma vez, a "
        "menos que o usuário confirme explicitamente; (4) enviar_texto_livre só chega se a "
        "pessoa mandou mensagem nas últimas 24h — a Meta pode responder OK sem entregar de "
        "verdade, então nunca confirme 'mensagem entregue' ao usuário só por causa do status "
        "200, deixe claro que é 'aceito pela API', entrega real não é garantida por esse status."
    ),
    stateless_http=True,
    streamable_http_path="/",  # evita URL final tipo /mcp/<segredo>/mcp — fica só /mcp/<segredo>
)

GRAPH_BASE = f"https://graph.facebook.com/{settings.meta_graph_api_version}"


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GRAPH_BASE,
        headers={"Authorization": f"Bearer {settings.meta_access_token}"},
        timeout=20.0,
    )


def normalizar_celular(tel: str) -> str | None:
    """Retorna E.164 sem + (ex: 5511987654321) ou None se não for celular BR válido.
    Números de 10 dígitos (sem o 9) ganham o 9 automaticamente."""
    digits = re.sub(r"\D", "", tel or "")
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]
    if len(digits) == 11 and digits[2] == "9":
        return "55" + digits
    if len(digits) == 13 and digits.startswith("55") and digits[4] == "9":
        return digits
    return None


async def _esta_em_optout(numero: str) -> bool:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(WhatsappOptout).where(WhatsappOptout.numero == numero))
        return r.scalar_one_or_none() is not None


async def _ja_enviado(numero: str) -> bool:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(MensagemOficialEnviada).where(
                MensagemOficialEnviada.numero == numero,
                MensagemOficialEnviada.status == "enviado",
            )
        )
        return r.scalar_one_or_none() is not None


async def _registrar_envio(
    numero: str, tipo: str, resumo: str, status: str, message_id: str = "", detalhe: str = ""
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            MensagemOficialEnviada(
                numero=numero,
                tipo=tipo,
                template_ou_resumo=resumo[:255],
                status=status,
                message_id=message_id,
                detalhe=detalhe[:2000] if detalhe else None,
            )
        )
        await db.commit()


def _dentro_horario_comercial() -> bool:
    agora = datetime.now(FUSO)
    return 8 <= agora.hour < 21


# ── Ferramentas de consulta ─────────────────────────────────────────────────────

@mcp.tool()
async def listar_templates() -> dict:
    """Lista os templates de mensagem da conta WhatsApp Business, com status de aprovação
    (APPROVED, PENDING, REJECTED), idioma e categoria."""
    async with _cliente() as c:
        r = await c.get(
            f"/{settings.meta_waba_id}/message_templates",
            params={"fields": "name,status,language,category"},
        )
        return r.json()


@mcp.tool()
async def checar_qualidade_numero() -> dict:
    """Retorna a qualificação atual do número (GREEN/YELLOW/RED/UNKNOWN) e status de
    verificação no WhatsApp Manager. Chame isso antes de qualquer campanha para uma lista."""
    async with _cliente() as c:
        r = await c.get(
            f"/{settings.meta_phone_number_id}",
            params={"fields": "quality_rating,name_status,verified_name,display_phone_number"},
        )
        return r.json()


@mcp.tool()
async def metricas_template(nome_template: str, dias: int = 7) -> dict:
    """Métricas de um template aprovado (enviadas/entregues/lidas/clicadas) nos últimos N dias,
    via Template Analytics da Meta."""
    async with _cliente() as c:
        tpl = await c.get(
            f"/{settings.meta_waba_id}/message_templates", params={"fields": "id,name,status"}
        )
        templates = tpl.json().get("data", [])
        alvo = next((t for t in templates if t["name"] == nome_template), None)
        if not alvo:
            return {"erro": f"Template '{nome_template}' não encontrado nessa conta."}

        fim = datetime.now(FUSO)
        inicio = fim - timedelta(days=dias)
        r = await c.get(
            f"/{settings.meta_waba_id}/template_analytics",
            params={
                "start": int(inicio.timestamp()),
                "end": int(fim.timestamp()),
                "granularity": "DAILY",
                "template_ids": alvo["id"],
                "metric_types": '["SENT","DELIVERED","READ","CLICKED"]',
            },
        )
        if r.status_code != 200:
            return {"erro": r.json(), "nota": "Endpoint de analytics da Meta pode ter mudado o formato — conferir resposta bruta."}
        return r.json()


@mcp.tool()
async def listar_optout() -> list[dict]:
    """Lista números que pediram para não receber mais mensagens (opt-out)."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(WhatsappOptout))
        return [
            {"numero": x.numero, "motivo": x.motivo, "criado_em": x.criado_em.isoformat()}
            for x in r.scalars().all()
        ]


@mcp.tool()
async def adicionar_optout(numero: str, motivo: str = "manual via agente") -> dict:
    """Registra manualmente um número como opt-out — nunca mais recebe mensagens desta conta."""
    numero_norm = normalizar_celular(numero) or re.sub(r"\D", "", numero)
    async with AsyncSessionLocal() as db:
        existente = await db.execute(select(WhatsappOptout).where(WhatsappOptout.numero == numero_norm))
        if existente.scalar_one_or_none():
            return {"status": "ja_estava_em_optout", "numero": numero_norm}
        db.add(WhatsappOptout(numero=numero_norm, motivo=motivo))
        await db.commit()
    return {"status": "adicionado", "numero": numero_norm}


# ── Envio individual ─────────────────────────────────────────────────────────────

@mcp.tool()
async def enviar_template(
    numero: str, nome_template: str, idioma: str = "pt_BR", variavel_nome: str | None = None
) -> dict:
    """Envia UM template aprovado para UM número — use para testes ou envios pontuais.
    Para listas, use iniciar_campanha. Bloqueia sozinho se o número estiver em opt-out."""
    numero_norm = normalizar_celular(numero) or re.sub(r"\D", "", numero)
    if await _esta_em_optout(numero_norm):
        return {"status": "bloqueado", "motivo": "número está em opt-out"}

    template: dict = {"name": nome_template, "language": {"code": idioma}}
    if variavel_nome:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": variavel_nome}]}
        ]

    async with _cliente() as c:
        r = await c.post(
            f"/{settings.meta_phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": numero_norm,
                "type": "template",
                "template": template,
            },
        )
    data = r.json()
    if r.status_code == 200:
        msg_id = data.get("messages", [{}])[0].get("id", "")
        await _registrar_envio(numero_norm, "template", nome_template, "enviado", message_id=msg_id)
        return {"status": "enviado", "message_id": msg_id}
    await _registrar_envio(numero_norm, "template", nome_template, "erro", detalhe=str(data))
    return {"status": "erro", "detalhe": data}


@mcp.tool()
async def enviar_texto_livre(numero: str, mensagem: str) -> dict:
    """Envia mensagem de texto livre (não-template) para UM número. SÓ chega de verdade se a
    pessoa mandou mensagem pra esse WhatsApp nas últimas 24h. Fora dessa janela a Meta pode
    responder 200 sem entregar — não informe ao usuário que "foi entregue" sem confirmação
    real (ex: o destinatário responder, ou checagem posterior)."""
    numero_norm = normalizar_celular(numero) or re.sub(r"\D", "", numero)
    if await _esta_em_optout(numero_norm):
        return {"status": "bloqueado", "motivo": "número está em opt-out"}

    async with _cliente() as c:
        r = await c.post(
            f"/{settings.meta_phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": numero_norm,
                "type": "text",
                "text": {"body": mensagem},
            },
        )
    data = r.json()
    if r.status_code == 200:
        msg_id = data.get("messages", [{}])[0].get("id", "")
        await _registrar_envio(numero_norm, "texto", mensagem[:80], "enviado", message_id=msg_id)
        return {
            "status": "aceito_pela_api",
            "message_id": msg_id,
            "aviso": "200 não garante entrega — a janela de 24h pode estar fechada.",
        }
    await _registrar_envio(numero_norm, "texto", mensagem[:80], "erro", detalhe=str(data))
    return {"status": "erro", "detalhe": data}


# ── Campanhas em lote (job em segundo plano) ─────────────────────────────────────

_JOBS: dict[str, dict] = {}


@mcp.tool()
async def iniciar_campanha(
    contatos: list[dict],
    nome_template: str,
    idioma: str = "pt_BR",
    limite: int | None = None,
    cadencia_min_seg: int = 20,
    cadencia_max_seg: int = 40,
) -> dict:
    """Dispara um template para uma LISTA de contatos, em segundo plano, respeitando horário
    comercial (8h-21h Brasília), cadência entre mensagens, opt-out e deduplicação (nunca reenvia
    quem já recebeu com sucesso). `contatos`: lista de {"numero": "...", "nome": "..." (opcional,
    vira a variável {{1}} do template se o template tiver uma)}. Retorna um job_id — use
    status_campanha(job_id) para acompanhar o progresso. Comece com `limite` baixo."""
    job_id = str(uuid.uuid4())[:8]
    pendentes = []
    for c in contatos:
        numero_norm = normalizar_celular(c.get("numero", ""))
        if not numero_norm:
            continue
        if await _esta_em_optout(numero_norm) or await _ja_enviado(numero_norm):
            continue
        pendentes.append({"numero": numero_norm, "nome": c.get("nome", "")})

    if limite:
        pendentes = pendentes[:limite]

    _JOBS[job_id] = {
        "status": "em_andamento",
        "total": len(pendentes),
        "enviados": 0,
        "erros": 0,
        "pendentes": len(pendentes),
    }
    asyncio.create_task(_rodar_campanha(job_id, pendentes, nome_template, idioma, cadencia_min_seg, cadencia_max_seg))
    return {"job_id": job_id, "total_pendentes": len(pendentes)}


async def _rodar_campanha(
    job_id: str,
    pendentes: list[dict],
    nome_template: str,
    idioma: str,
    cad_min: int,
    cad_max: int,
) -> None:
    for i, c in enumerate(pendentes):
        while not _dentro_horario_comercial():
            await asyncio.sleep(300)

        template: dict = {"name": nome_template, "language": {"code": idioma}}
        if c["nome"]:
            template["components"] = [
                {"type": "body", "parameters": [{"type": "text", "text": c["nome"]}]}
            ]

        async with _cliente() as cli:
            r = await cli.post(
                f"/{settings.meta_phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": c["numero"],
                    "type": "template",
                    "template": template,
                },
            )
        data = r.json()
        if r.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "")
            await _registrar_envio(c["numero"], "template", nome_template, "enviado", message_id=msg_id)
            _JOBS[job_id]["enviados"] += 1
        else:
            await _registrar_envio(c["numero"], "template", nome_template, "erro", detalhe=str(data))
            _JOBS[job_id]["erros"] += 1
        _JOBS[job_id]["pendentes"] = len(pendentes) - (i + 1)

        if i + 1 < len(pendentes):
            await asyncio.sleep(random.uniform(cad_min, cad_max))

    _JOBS[job_id]["status"] = "concluido"


@mcp.tool()
async def status_campanha(job_id: str) -> dict:
    """Consulta o progresso de uma campanha iniciada com iniciar_campanha. Jobs somem se o
    servidor reiniciar no meio — mas os envios já feitos ficam registrados (não duplicam)."""
    return _JOBS.get(job_id, {"status": "nao_encontrado"})
