from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import local_router, router
from app.core.config import get_settings
from app.core.db import engine
from app.models import Base
from app.workers.runner import requeue_interrupted, start_background, stop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    n = requeue_interrupted()
    if n:
        logging.info("requeued %s interrupted jobs", n)
    if os.getenv("DUB_WORKER_INLINE", "1") == "1":
        start_background()
    yield
    stop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # single-user app behind a private deployment
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(local_router, prefix="/api")


@app.get("/")
def root():
    return {"service": settings.app_name, "docs": "/docs", "api": "/api/health"}
