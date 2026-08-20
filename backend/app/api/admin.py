"""Admin API: runtime settings, log viewer, diagnostics, data management."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import logbuffer
from app.api.auth import require_admin
from app.notify import ALL_EVENTS
from app.race_engineer import CATEGORIES

if TYPE_CHECKING:
    from app.service import TelemetryService

log = logging.getLogger(__name__)

# The whole router is token-gated (when a token is configured): even the
# GETs leak secrets — /settings returns the webhook URL, which for Discord
# is itself a write credential; /stats and /logs expose LAN details.
router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

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
        "webhook_events": [e for e in ALL_EVENTS if e in s.enabled_webhook_events()],
        "packet_format": s.packet_format,
        "raw_archive": s.raw_archive,
        "race_engineer": s.race_engineer,
        "race_engineer_verbosity": s.race_engineer_verbosity,
        "race_engineer_categories": [c for c in CATEGORIES if c in s.enabled_callout_categories()],
        "race_engineer_units": s.race_engineer_units,
    }


class SettingsPayload(BaseModel):
    ps_ip: str | None = Field(default=None, max_length=64)
    source: Literal["udp", "sim"] | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_events: (
        list[Literal["personal_best", "session_summary", "overtake", "position_lost", "off_road"]]
        | None
    ) = None
    packet_format: Literal["A", "B", "~", "C"] | None = None
    raw_archive: bool | None = None
    race_engineer: bool | None = None
    race_engineer_verbosity: Literal["minimal", "race", "coach"] | None = None
    # Validated against app.race_engineer.CATEGORIES below rather than a
    # Literal, so the category list has exactly one definition.
    race_engineer_categories: list[str] | None = None
    race_engineer_units: Literal["metric", "imperial"] | None = None


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
    if (
        payload.packet_format is not None
        and payload.packet_format != service.settings.packet_format
    ):
        # The listener reads this on every heartbeat, so it applies live.
        service.settings.packet_format = payload.packet_format
        await service.repo.set_setting("packet_format", payload.packet_format)
        log.info("packet format set to %s", payload.packet_format)
    if payload.raw_archive is not None and payload.raw_archive != service.settings.raw_archive:
        service.set_raw_archive_enabled(payload.raw_archive)
        await service.repo.set_setting("raw_archive", str(payload.raw_archive).lower())
        log.info(
            "raw telemetry archival %s for the next session",
            "enabled" if payload.raw_archive else "disabled",
        )
    if payload.webhook_url is not None:
        url = payload.webhook_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(400, "webhook URL must start with http:// or https://")
        service.settings.webhook_url = url
        service.notifier.url = url
        await service.repo.set_setting("webhook_url", url)
        log.info("webhook %s", "configured" if url else "disabled")
    if payload.webhook_events is not None:
        spec = ",".join(dict.fromkeys(payload.webhook_events))  # dedupe, keep order
        service.settings.webhook_events = spec
        service.notifier.enabled = service.settings.enabled_webhook_events()
        await service.repo.set_setting("webhook_events", spec)
        log.info("webhook events: %s", spec or "none")
    await _apply_race_engineer(service, payload)
    return await get_settings(request)


async def _apply_race_engineer(service: TelemetryService, payload: SettingsPayload) -> None:
    """Race Engineer settings: env default, admin override, DB-persisted."""
    changed = False
    if payload.race_engineer is not None:
        service.settings.race_engineer = payload.race_engineer
        await service.repo.set_setting("race_engineer", str(payload.race_engineer).lower())
        changed = True
    if payload.race_engineer_verbosity is not None:
        service.settings.race_engineer_verbosity = payload.race_engineer_verbosity
        await service.repo.set_setting("race_engineer_verbosity", payload.race_engineer_verbosity)
        changed = True
    if payload.race_engineer_categories is not None:
        unknown = [c for c in payload.race_engineer_categories if c not in CATEGORIES]
        if unknown:
            raise HTTPException(400, f"unknown callout categories: {', '.join(unknown)}")
        spec = ",".join(dict.fromkeys(payload.race_engineer_categories))
        service.settings.race_engineer_categories = spec
        await service.repo.set_setting("race_engineer_categories", spec)
        changed = True
    if payload.race_engineer_units is not None:
        service.settings.race_engineer_units = payload.race_engineer_units
        await service.repo.set_setting("race_engineer_units", payload.race_engineer_units)
        changed = True
    if not changed:
        return
    service.engineer.configure(
        enabled=service.settings.race_engineer,
        verbosity=service.settings.race_engineer_verbosity,
        categories=service.settings.enabled_callout_categories(),
        units=service.settings.race_engineer_units,
    )
    service.publish_engineer_status()
    log.info(
        "race engineer: %s, %s verbosity",
        "enabled" if service.settings.race_engineer else "disabled",
        service.settings.race_engineer_verbosity,
    )


# --- race engineer diagnostics ----------------------------------------------


@router.get("/race-engineer")
async def race_engineer(request: Request) -> dict[str, Any]:
    service = svc(request)
    return {**service.engineer.diagnostics(), **service.engineer_status()}


class TestCalloutPayload(BaseModel):
    event_type: str = Field(default="test", max_length=64)
    text: str = Field(default="Race engineer test callout.", max_length=300)


@router.post("/race-engineer/test")
async def test_callout(request: Request, payload: TestCalloutPayload) -> dict[str, Any]:
    """Inject a callout so voice output can be verified without driving."""
    service = svc(request)
    callout = service.engineer.test_callout(payload.event_type, payload.text)
    service.publish_callout(callout)
    return callout.to_dict()


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


def _lan_ip() -> str:
    """This machine's LAN address (for overlay URLs used from other devices)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packet is sent; just picks a route
            ip: str = s.getsockname()[0]
            return ip
    except OSError:
        return ""


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
        "lan_ip": _lan_ip(),
        "http_port": service.settings.http_port,
    }


# --- actions ----------------------------------------------------------------


class ArchiveHydrationRequest(BaseModel):
    mode: Literal["stale_only", "retry_incomplete", "force_all"] = "retry_incomplete"


@router.get("/archive-hydration")
async def archive_hydration_status(request: Request) -> dict[str, Any]:
    return svc(request).hydration.status()


@router.post("/archive-hydration", status_code=202)
async def start_archive_hydration(
    request: Request, payload: ArchiveHydrationRequest
) -> dict[str, Any]:
    try:
        return await svc(request).hydration.start_job(payload.mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/restart-source")
async def restart_source(request: Request) -> dict[str, Any]:
    await svc(request).restart_source()
    return await svc(request).status()


@router.post("/clear-data")
async def clear_data(request: Request) -> dict[str, str]:
    service = svc(request)
    await service.clear_recorded_data()
    log.warning("all recorded sessions and laps deleted via admin")
    return {"status": "cleared"}


@router.post("/vacuum")
async def vacuum(request: Request) -> dict[str, str]:
    service = svc(request)
    if service.hydration.running:
        raise HTTPException(409, "archive hydration is running")
    await service.repo.vacuum()
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
