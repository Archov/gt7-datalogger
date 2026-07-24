"""Application entrypoint: FastAPI app serving the API, WebSocket, and SPA."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import logbuffer
from app.api import admin, routes, ws
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
    logbuffer.install()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("app")

    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))

    # Settings changed via the admin page override env defaults.
    stored = await repo.get_settings()
    if "ps_ip" in stored:
        settings.ps_ip = stored["ps_ip"]
    if stored.get("source") in ("udp", "sim"):
        settings.source = stored["source"]
    if "log_level" in stored:
        logging.getLogger().setLevel(stored["log_level"])
    if "webhook_url" in stored:
        settings.webhook_url = stored["webhook_url"]

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
    app.include_router(admin.router)
    app.include_router(ws.router)
    if FRONTEND_DIST.exists():
        # SPA deep link: /overlay?... must serve the app (the static mount
        # only resolves "/"). A plain path keeps strict URL validators happy
        # (some streaming apps reject /#overlay fragment URLs).
        @app.get("/overlay", include_in_schema=False)
        async def overlay_page() -> FileResponse:
            return FileResponse(FRONTEND_DIST / "index.html")

        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.http_host, port=settings.http_port)
