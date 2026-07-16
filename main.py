from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

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
# Montado na RAIZ ("/"), e por ÚLTIMO — precisa vir depois de tudo acima, senão o mount
# intercepta /health e os webhooks antes deles serem alcançados (Starlette casa rotas na
# ordem em que foram registradas, e um Mount("/") combina com qualquer path).
if settings.mcp_secret_path:
    app.mount("/", mcp.streamable_http_app())
else:
    print("AVISO: MCP_SECRET_PATH não configurado — servidor MCP do WhatsApp não foi montado.")
