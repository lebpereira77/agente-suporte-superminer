from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ── Tabela própria do agente ──────────────────────────────────────────────────

class SuporteConversa(Base):
    """Histórico de conversa WhatsApp por número de telefone."""

    __tablename__ = "suporte_conversas"

    phone = Column(String(20), primary_key=True)
    remote_jid = Column(String(80), nullable=True)    # JID completo (@s.whatsapp.net ou @lid)
    historico = Column(Text, nullable=True)          # JSON [{role, content}]
    modo_humano = Column(Boolean, default=False)      # True = bot pausado
    nome_usuario = Column(String(255), nullable=True)
    criado_em = Column(DateTime, default=_now)
    atualizado_em = Column(DateTime, default=_now)


# ── Tabelas lidas do banco do Super Miner (somente leitura) ───────────────────

class User(Base):
    """Usuário do Super Miner — apenas campos usados pelo agente."""

    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=True)
    nome = Column(String(255), nullable=True)
    organization_id = Column(String(36), nullable=True)


class SessaoMineracao(Base):
    """Sessão de mineração — apenas campos usados pelo agente."""

    __tablename__ = "sessoes_mineracao"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True)
    status = Column(String(20), nullable=True)
    etapa_atual = Column(String(255), nullable=True)
    total_produtos = Column(Integer, nullable=True)
    criado_em = Column(DateTime, nullable=True)
    organization_id = Column(String(36), nullable=True)


# ── Opt-out da campanha WhatsApp oficial (Cloud API) ───────────────────────────

class WhatsappOptout(Base):
    """Números que pediram para não receber mais mensagens da campanha oficial.
    Consultada pelo script execution/disparar_whatsapp_oficial.py antes de cada disparo."""

    __tablename__ = "whatsapp_optout"

    numero = Column(String(20), primary_key=True)
    motivo = Column(String(255), nullable=True)
    criado_em = Column(DateTime, default=_now)


class MensagemOficialEnviada(Base):
    """Log de envios feitos via mcp_server.py (agente no claude.ai). Independente do
    envios_oficial_log.csv local usado por execution/disparar_whatsapp_oficial.py —
    os dois não se enxergam, cada um deduplica só dentro do próprio caminho de envio."""

    __tablename__ = "whatsapp_mensagens_enviadas"

    id = Column(String(36), primary_key=True, default=_uuid)
    numero = Column(String(20), index=True)
    tipo = Column(String(20))  # template | texto
    template_ou_resumo = Column(String(255), nullable=True)
    status = Column(String(20))  # enviado | erro
    message_id = Column(String(255), nullable=True)
    detalhe = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=_now)
