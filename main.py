from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Mount, Route

from config import settings
from database import init_db
from mcp_server import mcp
from webhook import router
from webhook_oficial import router as router_oficial


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        # Necessário pro FastMCP processar sessões do endpoint /mcp/... montado abaixo —
        # sem isso o transporte streamable-http não inicializa (gotcha conhecido do SDK
        # ao montar FastMCP como sub-app dentro de outro FastAPI).
        await stack.enter_async_context(mcp.session_manager.run())
        await init_db()
        print("Agente de Suporte Super Miner — pronto")
        yield


app = FastAPI(title="Agente Suporte Super Miner", lifespan=lifespan)
app.include_router(router)
app.include_router(router_oficial)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Duas camadas: segredo no caminho da URL (embutido em streamable_http_path, dentro de
# mcp_server.py) + OAuth (oauth_provider.py) por cima. O OAuth sozinho não bastaria — o
# /authorize aprova qualquer client automaticamente (uso pessoal, sem tela de login), então
# o segredo no path é o que impede acesso de quem não tem a URL.
#
# TUDO (ferramentas + rotas OAuth: /register, /authorize, /token, /.well-known/...) fica
# dentro do mesmo mount, sob o caminho secreto. Testei montar só as ferramentas ali e deixar
# as rotas OAuth na raiz do domínio (mais "correto" pro RFC 8414), mas o claude.ai não usa o
# registration_endpoint absoluto da descoberta — ele sempre tenta POST <connector>/register
# relativo ao próprio caminho do Connector (confirmado nos logs de produção). Então tudo
# precisa estar aninhado junto.
if settings.mcp_secret_path:
    _secret = settings.mcp_secret_path
    _prefix = f"/mcp/{_secret}"
    _mcp_app = mcp.streamable_http_app()
    _mount = Mount(_prefix, app=_mcp_app)

    class _ReescreverEDelegar:
        """O claude.ai tenta várias convenções diferentes pra descobrir/registrar OAuth —
        algumas relativas ao caminho do Connector, outras na raiz do domínio, com e sem
        barra final — e não segue redirects nem cai pra próxima tentativa se a primeira
        rota "certa" (pelo RFC) não existir. Confirmado nos logs de produção, tentativa a
        tentativa, quais formatos ele realmente usa.

        Em vez de adivinhar mais, cada formato observado ganha uma rota explícita aqui que
        reescreve o path pro caminho interno de verdade (dentro do mount /mcp/<segredo>) e
        delega via `Mount.matches()` — o mesmo caminho de código que já funciona, só
        redirecionado por dentro em vez de por HTTP (registrar a rota/endpoint direto, sem
        passar pelo Mount, quebrava a leitura do token pela auth middleware)."""

        def __init__(self, mount: Mount, caminho_interno: str) -> None:
            self.mount = mount
            self.caminho_interno = caminho_interno

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["path"] = self.caminho_interno
            scope.pop("raw_path", None)
            _, child_scope = self.mount.matches(scope)
            merged_scope = {**scope, **child_scope}
            await child_scope["endpoint"](merged_scope, receive, send)

    def _rota(caminho_externo: str, caminho_interno: str) -> Route:
        return Route(caminho_externo, endpoint=_ReescreverEDelegar(_mount, caminho_interno))

    # Formatos observados nos logs reais do claude.ai, em tentativas diferentes:
    app.router.routes.append(_rota(_prefix, f"{_prefix}/"))  # POST sem barra
    app.router.routes.append(
        _rota(
            f"/.well-known/oauth-protected-resource{_prefix}/",
            f"{_prefix}/.well-known/oauth-protected-resource{_prefix}/",
        )
    )
    app.router.routes.append(
        _rota(
            f"/.well-known/oauth-protected-resource{_prefix}",
            f"{_prefix}/.well-known/oauth-protected-resource{_prefix}/",
        )
    )
    app.router.routes.append(
        _rota("/.well-known/oauth-protected-resource", f"{_prefix}/.well-known/oauth-protected-resource{_prefix}/")
    )
    app.router.routes.append(
        _rota("/.well-known/oauth-authorization-server", f"{_prefix}/.well-known/oauth-authorization-server")
    )
    app.router.routes.append(_rota("/register", f"{_prefix}/register"))
    app.router.routes.append(_rota("/authorize", f"{_prefix}/authorize"))
    app.router.routes.append(_rota("/token", f"{_prefix}/token"))
    app.router.routes.append(_rota("/revoke", f"{_prefix}/revoke"))

    app.router.routes.append(_mount)
else:
    print("AVISO: MCP_SECRET_PATH não configurado — servidor MCP do WhatsApp não foi montado.")
