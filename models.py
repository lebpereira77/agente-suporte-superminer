from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


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
