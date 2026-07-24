"""Admin API: runtime settings, log viewer, diagnostics, data management."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import logbuffer

if TYPE_CHECKING:
    from app.service import TelemetryService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")

CARS_URL = "https://raw.githubusercontent.com/ddm999/gt7info/web-new/_data/db/cars.csv"


def svc(request: Request) -> TelemetryService:
    service: TelemetryService = request.app.state.service
    return service


# --- settings ---------------------------------------------------------------


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    s = svc(request).settings
    return {
        "ps_ip": s.ps_ip,
        "source": s.source,
        "log_level": logging.getLevelName(logging.getLogger().level),
        "ws_rate": s.ws_rate,
        "heartbeat_port": s.heartbeat_port,
        "telemetry_port": s.telemetry_port,
        "webhook_url": s.webhook_url,
    }


class SettingsPayload(BaseModel):
    ps_ip: str | None = Field(default=None, max_length=64)
    source: Literal["udp", "sim"] | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None
    webhook_url: str | None = Field(default=None, max_length=500)


@router.put("/settings")
async def put_settings(request: Request, payload: SettingsPayload) -> dict[str, Any]:
    service = svc(request)
    if payload.ps_ip is not None and payload.ps_ip != service.settings.ps_ip:
        ip = payload.ps_ip.strip()
        if ip and not _looks_like_host(ip):
            raise HTTPException(400, "not a valid IP address or hostname")
        await service.set_ps_ip(ip)
        await service.repo.set_setting("ps_ip", ip)
    if payload.source is not None and payload.source != service.settings.source:
        await service.switch_source(payload.source)
        await service.repo.set_setting("source", payload.source)
    if payload.log_level is not None:
        logging.getLogger().setLevel(payload.log_level)
        await service.repo.set_setting("log_level", payload.log_level)
        log.info("log level set to %s", payload.log_level)
    if payload.webhook_url is not None:
        url = payload.webhook_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(400, "webhook URL must start with http:// or https://")
        service.settings.webhook_url = url
        service.notifier.url = url
        await service.repo.set_setting("webhook_url", url)
        log.info("webhook %s", "configured" if url else "disabled")
    return await get_settings(request)


@router.post("/test-webhook")
async def test_webhook(request: Request) -> dict[str, str]:
    service = svc(request)
    if not service.notifier.url:
        raise HTTPException(400, "no webhook URL configured")
    try:
        await service.notifier.send(
            "test", "🔧 GT7 Datalogger test", [("Status", "webhook configured correctly")]
        )
    except Exception as exc:  # noqa: BLE001 - report any delivery failure
        raise HTTPException(502, f"webhook delivery failed: {exc}") from exc
    return {"status": "sent"}


def _looks_like_host(value: str) -> bool:
    if any(c.isspace() for c in value):
        return False
    parts = value.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return all(0 <= int(p) <= 255 for p in parts)
    # allow hostnames / mDNS names
    return all(p and all(c.isalnum() or c == "-" for c in p) for p in value.split("."))


# --- logs -------------------------------------------------------------------


@router.get("/logs")
async def get_logs(
    limit: int = Query(300, ge=1, le=2000),
    level: str | None = Query(None),
) -> list[dict[str, Any]]:
    return logbuffer.records(limit=limit, level=level)


@router.delete("/logs")
async def clear_logs() -> dict[str, str]:
    logbuffer.clear()
    return {"status": "cleared"}


# --- diagnostics ------------------------------------------------------------


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    service = svc(request)
    db_stats = await service.repo.stats()
    db_path = service.settings.db_path
    db_size = db_path.stat().st_size if db_path.exists() else 0
    return {
        "uptime_s": int(time.time() - service.started_at),
        "db": {**db_stats, "size_bytes": db_size, "path": str(db_path)},
        "cars_loaded": service.cars.count,
        "source": await service.status(),
        "clients": service.client_count,
    }


# --- actions ----------------------------------------------------------------


@router.post("/restart-source")
async def restart_source(request: Request) -> dict[str, Any]:
    await svc(request).restart_source()
    return await svc(request).status()


@router.post("/clear-data")
async def clear_data(request: Request) -> dict[str, str]:
    service = svc(request)
    await service.repo.clear_all()
    service.session_id = None
    log.warning("all recorded sessions and laps deleted via admin")
    return {"status": "cleared"}


@router.post("/vacuum")
async def vacuum(request: Request) -> dict[str, str]:
    await svc(request).repo.vacuum()
    return {"status": "ok"}


@router.post("/update-cars")
async def update_cars(request: Request) -> dict[str, Any]:
    """Download the community car list and reload the lookup table."""
    service = svc(request)
    path = service.settings.cars_csv

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(CARS_URL)
            resp.raise_for_status()
            raw = resp.text
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"download failed: {exc}") from exc

    import csv
    import io

    reader = csv.DictReader(io.StringIO(raw))
    fields = {f.lower(): f for f in reader.fieldnames or []}
    id_col = fields.get("id")
    name_col = fields.get("shortname") or fields.get("name")
    if not id_col or not name_col:
        raise HTTPException(502, f"unexpected columns from upstream: {reader.fieldnames}")
    rows = [(row[id_col], row[name_col]) for row in reader if row.get(id_col)]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name"])
        writer.writerows(rows)
    service.cars.load(path)
    log.info("car database updated: %d cars", len(rows))
    return {"cars": len(rows)}
