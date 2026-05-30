"""Agente Claude de suporte via WhatsApp."""
from __future__ import annotations

import json

import anthropic
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import SessaoMineracao, SuporteConversa, User

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_MAX_HISTORICO = 20

_SYSTEM_PROMPT = """Você é o agente de suporte do Super Miner, assistente especializado para ajudar vendedores FBA da Amazon Brasil a usar a plataforma.

## O que é o Super Miner
Plataforma SaaS de sourcing inteligente: importa catálogos de fornecedores, cruza com dados da Amazon e identifica produtos rentáveis para revenda FBA.

## Funcionalidades principais

### 1. Fornecedores e Catálogos
- Cadastrar fornecedores e importar catálogos em PDF, Excel/CSV ou scraping do site do fornecedor
- Cada produto do catálogo recebe análise de viabilidade FBA (ROI, margem, lucro estimado)

### 2. Sessão de Mineração
- Analisa produtos do catálogo contra a Amazon automaticamente
- Para cada produto: busca ASIN correspondente, coleta preço/BSR/demanda, calcula viabilidade
- Resultados: ✅ Aprovado (ROI ≥ 25%, margem ≥ 12%), ⚠️ Atenção, ❌ Reprovado, 🔍 Revisão (match incerto)
- Pode usar pool de ASINs para acelerar

### 3. Super Filter
- Filtra produtos da Amazon com alta demanda
- Filtros: categoria, marca, faixa de vendas/mês, preço, BSR, avaliações, número de vendedores
- Exporta lista de ASINs qualificados → vira "pool" para mineração

### 4. Pool de ASINs
- Lista de ASINs pré-selecionados do Super Filter com demanda confirmada
- Usado em sessões de mineração no modo invertido: parte dos ASINs e busca correspondentes no catálogo
- Muito mais rápido que mineração clássica para catálogos grandes

### 5. Resultados e Exportação
- Visualizar por sessão com filtros (Aprovados, Atenção, Revisão, Reprovados)
- Exportar relatório XLSX com todos os produtos analisados
- Ver detalhes: preço Amazon, BSR, estimativa de vendas/mês, taxas FBA, margem, ROI

## Configurações
- Tarifas FBA: aba Configurações > Tarifas
- Thresholds de aprovação: ROI mínimo e margem mínima configuráveis
- ASIN Memory: lembra ASINs já analisados para evitar repetição

## Fluxo de uso típico
1. Criar conta (feito por Eduardo manualmente — beta fechado)
2. Acessar /bem-vindo e fazer o onboarding guiado
3. Adicionar fornecedor em Fornecedores
4. Importar catálogo (PDF, Excel ou URL do site)
5. Iniciar sessão de mineração
6. Analisar resultados e exportar relatório

## Problemas comuns e soluções
- **Sessão travada / sem progresso**: atualizar a página; se persistir, cancelar e criar nova sessão
- **"Tela preta" ao abrir resultado**: fazer refresh; se persistir, reportar
- **ASIN não encontrado**: produto pode não ter correspondente na Amazon BR ou nome muito genérico
- **Erro ao importar catálogo**: verificar formato (PDF nativo, não escaneado; Excel com colunas de nome e preço)
- **Super Filter retornando 0 resultados**: verificar filtros; demanda mínima pode estar alta; tentar sem filtro de marca
- **Sessão em "erro"**: não reusar — criar nova sessão (resultados parciais são preservados)

## Acesso e conta
- App em: https://super-miner.vercel.app
- Login com e-mail e senha recebidos por mensagem/e-mail
- Beta fechado: novos acessos apenas com aprovação de Eduardo (eduardo@inovartia.com)
- Planos: Starter (R$97/mês), Pro (R$247/mês), Scale (R$497/mês) — durante o beta, acesso gratuito

## Seu comportamento
- Responda em português do Brasil, de forma concisa e direta
- Mensagens curtas e adequadas para WhatsApp (sem markdown pesado)
- Se não souber a resposta, diga que vai verificar com a equipe
- Para problemas técnicos graves ou quando o usuário pedir humano, use `escalar_para_humano`
- Para consultar dados reais do usuário, use as ferramentas disponíveis
- Nunca invente funcionalidades que não existem
"""

_TOOLS = [
    {
        "name": "buscar_usuario",
        "description": "Busca informações da conta do usuário no Super Miner pelo e-mail, caso o usuário informe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "E-mail do usuário"}
            },
            "required": ["email"],
        },
    },
    {
        "name": "buscar_sessoes_usuario",
        "description": "Busca as sessões de mineração recentes do usuário para diagnóstico de problemas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "organization_id": {"type": "string", "description": "ID da organização do usuário"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["organization_id"],
        },
    },
    {
        "name": "escalar_para_humano",
        "description": "Escala a conversa para Eduardo (suporte humano). Use quando: problema técnico grave, solicitação de reembolso, acesso negado, ou usuário pediu explicitamente falar com humano.",
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {"type": "string", "description": "Resumo do problema e motivo da escalação"},
                "resumo_conversa": {"type": "string", "description": "Resumo das últimas mensagens"},
            },
            "required": ["motivo"],
        },
    },
]


async def _executar_tool(
    tool_name: str,
    tool_input: dict,
    phone: str,
    db: AsyncSession,
) -> str:
    try:
        if tool_name == "buscar_usuario":
            return await _tool_buscar_usuario(tool_input["email"], db)
        elif tool_name == "buscar_sessoes_usuario":
            return await _tool_buscar_sessoes(tool_input["organization_id"], tool_input.get("limit", 5), db)
        elif tool_name == "escalar_para_humano":
            return await _tool_escalar(phone, tool_input["motivo"], tool_input.get("resumo_conversa", ""), db)
        else:
            return f"Ferramenta desconhecida: {tool_name}"
    except Exception as e:
        return f"Erro ao executar a ferramenta: {e}"


async def _tool_buscar_usuario(email: str, db: AsyncSession) -> str:
    result = await db.execute(select(User).where(User.email == email).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        return "Usuário não encontrado."
    return json.dumps({
        "id": user.id,
        "nome": user.nome or "N/A",
        "email": user.email,
        "organization_id": user.organization_id,
    }, ensure_ascii=False)


async def _tool_buscar_sessoes(organization_id: str, limit: int, db: AsyncSession) -> str:
    result = await db.execute(
        select(SessaoMineracao)
        .where(SessaoMineracao.organization_id == organization_id)
        .order_by(desc(SessaoMineracao.criado_em))
        .limit(min(limit, 10))
    )
    sessoes = result.scalars().all()
    if not sessoes:
        return "Nenhuma sessão de mineração encontrada."
    dados = [
        {
            "id": s.id[:8] + "...",
            "status": s.status,
            "etapa": s.etapa_atual,
            "produtos": s.total_produtos,
            "criado_em": str(s.criado_em)[:16] if s.criado_em else None,
        }
        for s in sessoes
    ]
    return json.dumps(dados, ensure_ascii=False)


async def _tool_escalar(phone: str, motivo: str, resumo: str, db: AsyncSession) -> str:
    from evolution_service import enviar_mensagem

    result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == phone))
    conversa = result.scalar_one_or_none()
    if conversa:
        conversa.modo_humano = True
        await db.commit()

    msg_eduardo = (
        f"🔔 *Novo ticket de suporte*\n"
        f"📱 Usuário: {phone}\n"
        f"🔍 Motivo: {motivo}"
    )
    if resumo:
        msg_eduardo += f"\n\n💬 Contexto: {resumo}"
    msg_eduardo += f"\n\nPara reativar o bot: *!retomar {phone}*"

    await enviar_mensagem(settings.suporte_eduardo_phone, msg_eduardo)
    return "Escalação registrada. Eduardo foi notificado e irá entrar em contato em breve."


async def processar_mensagem(phone: str, texto: str, db: AsyncSession) -> str:
    """Processa mensagem do usuário e retorna resposta do agente."""
    result = await db.execute(select(SuporteConversa).where(SuporteConversa.phone == phone))
    conversa = result.scalar_one_or_none()

    if not conversa:
        conversa = SuporteConversa(phone=phone)
        db.add(conversa)

    historico: list[dict] = json.loads(conversa.historico) if conversa.historico else []
    historico.append({"role": "user", "content": texto})

    messages = [{"role": h["role"], "content": h["content"]} for h in historico[-_MAX_HISTORICO:]]

    resposta_final = ""
    for _ in range(5):
        response = await _client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        tool_calls = []
        texto_parcial = ""
        for block in response.content:
            if block.type == "text":
                texto_parcial += block.text
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})

        if response.stop_reason == "end_turn" or not tool_calls:
            resposta_final = texto_parcial
            historico.append({"role": "assistant", "content": texto_parcial})
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tc in tool_calls:
            resultado = await _executar_tool(tc["name"], tc["input"], phone, db)
            tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": resultado})
        messages.append({"role": "user", "content": tool_results})

    if len(historico) > _MAX_HISTORICO:
        historico = historico[-_MAX_HISTORICO:]

    conversa.historico = json.dumps(historico, ensure_ascii=False)
    await db.commit()

    return resposta_final or "Desculpe, não consegui processar sua mensagem. Tente novamente."
