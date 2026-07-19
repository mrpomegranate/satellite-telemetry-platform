"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import cors_origins
from .db import close_pool, fetch_one, open_pool
from .routers import catalog, groups, labels, registry, timeseries


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    yield
    await close_pool()


app = FastAPI(
    title="telemetry-platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(timeseries.router)
app.include_router(groups.router)
app.include_router(labels.router)
app.include_router(registry.router)


@app.get("/health")
async def health():
    row = await fetch_one("SELECT 1 AS ok")
    return {"status": "ok", "db": bool(row and row["ok"] == 1)}
