from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import course, groups, login, preset, snipe
from app.config import settings
from app.core.auth_adapter import auth_adapter
from app.core.swust_client import swust_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await auth_adapter.aclose()
    await swust_client.aclose()


app = FastAPI(title="AntiSWUST 教务辅助系统", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(login.router)
app.include_router(course.router)
app.include_router(snipe.router)
app.include_router(groups.router)
app.include_router(preset.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
