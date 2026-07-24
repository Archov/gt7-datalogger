"""Application entrypoint: FastAPI app serving the API, WebSocket, and SPA."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import routes, ws
from app.config import get_settings
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("app")

    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))

    cars = CarDatabase()
    cars.load(settings.cars_csv)

    service = TelemetryService(settings, repo, cars)
    app.state.service = service
    await service.start()

    if settings.source == "udp" and not settings.ps_ip:
        log.info(
            "GT7_PS_IP not set: broadcasting heartbeat for auto-discovery. "
            "If no data arrives, check the console IP and that UDP %d is not firewalled.",
            settings.telemetry_port,
        )
    yield
    await service.stop()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="GT7 Datalogger", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.router)
    app.include_router(ws.router)
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.http_host, port=settings.http_port)
