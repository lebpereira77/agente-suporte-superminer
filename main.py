from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from database import init_db
from webhook import router
from webhook_oficial import router as router_oficial


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("Agente de Suporte Super Miner — pronto")
    yield


app = FastAPI(title="Agente Suporte Super Miner", lifespan=lifespan)
app.include_router(router)
app.include_router(router_oficial)


@app.get("/health")
async def health():
    return {"status": "ok"}
