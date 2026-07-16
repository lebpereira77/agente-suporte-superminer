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
    _mcp_app = mcp.streamable_http_app()
    _mount = Mount(f"/mcp/{settings.mcp_secret_path}", app=_mcp_app)

    class _SemBarraFinal:
        """O claude.ai testa a URL do Connector com POST /mcp/<segredo> (SEM barra) e não
        segue o redirect 307 que o Mount manda por padrão (a rota interna exige a barra) —
        ele só reporta "não foi possível conectar", sem tentar de novo.

        Registrar a mesma rota/endpoint direto (sem Mount) pra esse caminho exato quebrava a
        leitura do token pela auth middleware (scope/root_path diferente do que ela espera).
        Em vez disso, reescreve o path adicionando a barra e reusa o `Mount.matches()` de
        verdade — o mesmíssimo caminho de código que já funciona pra .../<segredo>/."""

        def __init__(self, mount: Mount) -> None:
            self.mount = mount

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["path"] = scope["path"] + "/"
            if scope.get("raw_path"):
                scope["raw_path"] = scope["raw_path"] + b"/"
            match, child_scope = self.mount.matches(scope)
            merged_scope = {**scope, **child_scope}
            await child_scope["endpoint"](merged_scope, receive, send)

    app.router.routes.append(
        Route(f"/mcp/{settings.mcp_secret_path}", endpoint=_SemBarraFinal(_mount))
    )
    app.router.routes.append(_mount)
else:
    print("AVISO: MCP_SECRET_PATH não configurado — servidor MCP do WhatsApp não foi montado.")
