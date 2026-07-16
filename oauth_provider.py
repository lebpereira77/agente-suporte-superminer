"""OAuth Authorization Server mínimo — só pra satisfazer o registro de Connector do
claude.ai (Dynamic Client Registration + Authorization Code + PKCE).

Uso pessoal/single-user: não existe tela de login porque não existe usuário além de quem
já tem a URL do servidor. Qualquer client que se registrar é aprovado automaticamente no
/authorize, sem intervenção manual. Isso é aceitável aqui porque (1) só uma pessoa usa este
servidor, (2) a URL do MCP continua com o segredo no path como camada extra, e (3) os únicos
dados que essas credenciais liberam são as ferramentas de WhatsApp já protegidas por opt-out
e outras checagens — não é um sistema multiusuário nem expõe dados de terceiros.
"""
from __future__ import annotations

import json
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete

from database import AsyncSessionLocal
from models import OAuthAccessTok, OAuthAuthCode, OAuthClient, OAuthRefreshTok

ACCESS_TOKEN_TTL = 3600  # 1h
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 180  # 180 dias
AUTH_CODE_TTL = 300  # 5 min


class SingleUserOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthClient, client_id)
            if not row:
                return None
            return OAuthClientInformationFull(
                client_id=row.client_id,
                client_secret=row.client_secret,
                redirect_uris=json.loads(row.redirect_uris),
                grant_types=json.loads(row.grant_types),
                response_types=json.loads(row.response_types),
                token_endpoint_auth_method=row.token_endpoint_auth_method,
                scope=row.scope,
                client_name=row.client_name,
            )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_secret=client_info.client_secret,
                    redirect_uris=json.dumps([str(u) for u in (client_info.redirect_uris or [])]),
                    grant_types=json.dumps(client_info.grant_types),
                    response_types=json.dumps(client_info.response_types),
                    token_endpoint_auth_method=client_info.token_endpoint_auth_method,
                    scope=client_info.scope,
                    client_name=client_info.client_name,
                )
            )
            await db.commit()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        # Sem tela de consentimento — aprova direto (ver docstring do módulo).
        code = secrets.token_urlsafe(32)
        async with AsyncSessionLocal() as db:
            db.add(
                OAuthAuthCode(
                    code=code,
                    client_id=client.client_id,
                    code_challenge=params.code_challenge,
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    scopes=json.dumps(params.scopes or []),
                    resource=params.resource,
                    expires_at=int(time.time()) + AUTH_CODE_TTL,
                )
            )
            await db.commit()
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthAuthCode, authorization_code)
            if not row:
                return None
            return AuthorizationCode(
                code=row.code,
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=row.redirect_uri,
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                scopes=json.loads(row.scopes),
                resource=row.resource,
                expires_at=row.expires_at,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        async with AsyncSessionLocal() as db:
            db.add(
                OAuthAccessTok(
                    token=access_token,
                    client_id=client.client_id,
                    scopes=json.dumps(authorization_code.scopes),
                    resource=authorization_code.resource,
                    expires_at=int(time.time()) + ACCESS_TOKEN_TTL,
                )
            )
            db.add(
                OAuthRefreshTok(
                    token=refresh_token,
                    client_id=client.client_id,
                    scopes=json.dumps(authorization_code.scopes),
                    expires_at=int(time.time()) + REFRESH_TOKEN_TTL,
                )
            )
            await db.execute(delete(OAuthAuthCode).where(OAuthAuthCode.code == authorization_code.code))
            await db.commit()
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthRefreshTok, refresh_token)
            if not row:
                return None
            return RefreshToken(
                token=row.token,
                client_id=row.client_id,
                scopes=json.loads(row.scopes),
                expires_at=row.expires_at,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        novo_refresh = secrets.token_urlsafe(32)
        async with AsyncSessionLocal() as db:
            db.add(
                OAuthAccessTok(
                    token=access_token,
                    client_id=client.client_id,
                    scopes=json.dumps(scopes),
                    expires_at=int(time.time()) + ACCESS_TOKEN_TTL,
                )
            )
            db.add(
                OAuthRefreshTok(
                    token=novo_refresh,
                    client_id=client.client_id,
                    scopes=json.dumps(scopes),
                    expires_at=int(time.time()) + REFRESH_TOKEN_TTL,
                )
            )
            await db.execute(delete(OAuthRefreshTok).where(OAuthRefreshTok.token == refresh_token.token))
            await db.commit()
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=novo_refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthAccessTok, token)
            if not row:
                return None
            if row.expires_at and row.expires_at < time.time():
                return None
            return AccessToken(
                token=row.token,
                client_id=row.client_id,
                scopes=json.loads(row.scopes),
                expires_at=row.expires_at,
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(OAuthAccessTok).where(OAuthAccessTok.token == token.token))
            await db.execute(delete(OAuthRefreshTok).where(OAuthRefreshTok.token == token.token))
            await db.commit()
