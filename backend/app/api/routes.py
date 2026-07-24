"""REST API for sessions, laps, analysis, and controls."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.processing import analysis
from app.processing.tracks import signature_from_samples

if TYPE_CHECKING:
    from app.service import TelemetryService

router = APIRouter(prefix="/api")


def svc(request: Request) -> TelemetryService:
    service: TelemetryService = request.app.state.service
    return service


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return await svc(request).status()


# --- sessions & laps --------------------------------------------------------


@router.get("/sessions")
async def sessions(request: Request) -> list[dict[str, Any]]:
    return await svc(request).repo.list_sessions()


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: int) -> dict[str, str]:
    await svc(request).repo.delete_session(session_id)
    return {"status": "deleted"}


@router.get("/sessions/{session_id}/laps")
async def session_laps(request: Request, session_id: int) -> list[dict[str, Any]]:
    laps = await svc(request).repo.list_laps(session_id)
    cars = svc(request).cars
    for lap in laps:
        lap["car_name"] = cars.name(lap["car_id"])
    return laps


@router.get("/laps")
async def laps(request: Request) -> list[dict[str, Any]]:
    laps = await svc(request).repo.list_laps()
    cars = svc(request).cars
    for lap in laps:
        lap["car_name"] = cars.name(lap["car_id"])
    return laps


@router.get("/laps/{lap_id}")
async def lap_detail(request: Request, lap_id: int) -> dict[str, Any]:
    lap = await svc(request).repo.get_lap(lap_id)
    if lap is None:
        raise HTTPException(404, "lap not found")
    lap["car_name"] = svc(request).cars.name(lap["car_id"])
    return lap


@router.delete("/laps/{lap_id}")
async def delete_lap(request: Request, lap_id: int) -> dict[str, str]:
    await svc(request).repo.delete_lap(lap_id)
    return {"status": "deleted"}


@router.get("/laps/{lap_id}/export")
async def export_lap(request: Request, lap_id: int) -> dict[str, Any]:
    data = await svc(request).repo.export_lap(lap_id)
    if data is None:
        raise HTTPException(404, "lap not found")
    return data


# Channel map for CSV export: sample column -> (display name, unit).
CSV_CHANNELS = (
    ("t", "Time", "s"),
    ("dist", "Distance", "m"),
    ("speed", "Ground Speed", "km/h"),
    ("throttle", "Throttle Pos", "%"),
    ("brake", "Brake Pos", "%"),
    ("gear", "Gear", ""),
    ("rpm", "Engine RPM", "rpm"),
    ("boost", "Boost Pressure", "bar"),
    ("tire_slip", "Tyre Slip Ratio", ""),
    ("yaw_rate", "Yaw Rate", "rad/s"),
    ("pos_x", "Pos X", "m"),
    ("pos_z", "Pos Z", "m"),
    ("body_height", "Ride Height", "mm"),
    ("fuel", "Fuel Level", "L"),
)


@router.get("/laps/{lap_id}/export.csv")
async def export_lap_csv(request: Request, lap_id: int) -> PlainTextResponse:
    """MoTeC-compatible CSV export (i2 'CSV file' import, Excel, etc.)."""
    lap = await svc(request).repo.get_lap(lap_id, with_samples=True)
    if lap is None:
        raise HTTPException(404, "lap not found")
    samples = lap["samples"]
    cols = [c for c in CSV_CHANNELS if c[0] in samples]
    time_ms = lap["time_ms"]
    duration = f"{time_ms // 60000}:{(time_ms % 60000) / 1000:06.3f}"
    car = svc(request).cars.name(lap["car_id"])

    lines = [
        '"Format","MoTeC CSV File"',
        '"Device","GT7 Datalogger"',
        f'"Vehicle","{car}"',
        f'"Comment","Lap {lap["number"]} - {duration}"',
        f'"Log Date","{lap.get("finished_at", "")}"',
        '"Sample Rate","60.000"',
        "",
        ",".join(f'"{name}"' for _, name, _ in cols),
        ",".join(f'"{unit}"' for _, _, unit in cols),
    ]
    n = len(samples["t"])
    for i in range(n):
        lines.append(
            ",".join(
                str(samples[key][i]) if i < len(samples[key]) else ""
                for key, _, _ in cols
            )
        )

    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="gt7-lap-{lap_id}.csv"'},
    )


# --- tracks -----------------------------------------------------------------


@router.get("/tracks")
async def tracks(request: Request) -> list[dict[str, Any]]:
    return await svc(request).repo.list_tracks()


class TrackPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lap_id: int


@router.post("/tracks")
async def create_track(request: Request, payload: TrackPayload) -> dict[str, Any]:
    """Name the circuit a lap was driven on; future sessions auto-match it."""
    service = svc(request)
    lap = await service.repo.get_lap(payload.lap_id, with_samples=True)
    if lap is None:
        raise HTTPException(404, "lap not found")
    sig = signature_from_samples(lap["samples"])
    if sig is None:
        raise HTTPException(400, "lap has no position data")
    name = payload.name.strip()
    track_id = await service.repo.create_track(name, sig)
    await service.repo.set_session_track(lap["session_id"], name)
    if service.session_id == lap["session_id"]:
        service.track_name = name
    return {"id": track_id, "name": name}


@router.delete("/tracks/{track_id}")
async def delete_track(request: Request, track_id: int) -> dict[str, str]:
    await svc(request).repo.delete_track(track_id)
    return {"status": "deleted"}


class ImportPayload(BaseModel):
    format: str
    version: int
    lap: dict[str, Any]


@router.post("/laps/import")
async def import_lap(request: Request, payload: ImportPayload) -> dict[str, Any]:
    service = svc(request)
    if service.session_id is None:
        from app.processing.laps import SessionInfo

        info = SessionInfo(car_id=payload.lap.get("car_id", 0), started_at="imported")
        service.session_id = await service.repo.create_session(
            info, service.cars.name(info.car_id)
        )
    try:
        lap_id = await service.repo.import_lap(payload.model_dump(), service.session_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"invalid lap file: {exc}") from exc
    return {"id": lap_id}


# --- analysis ---------------------------------------------------------------

COMPARE_COLUMNS = (
    "t", "speed", "throttle", "brake", "coast", "gear", "rpm", "boost", "tire_slip", "yaw_rate",
    "pos_x", "pos_z",
)


@router.get("/analysis/compare")
async def compare(
    request: Request,
    laps: str = Query(..., description="comma-separated lap ids"),
    ref: int = Query(..., description="reference lap id"),
    step: float = Query(5.0, gt=0.5, le=50),
) -> dict[str, Any]:
    """Distance-resampled series for each lap + time delta vs the reference."""
    try:
        lap_ids = [int(x) for x in laps.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(400, "laps must be comma-separated integers") from exc
    if ref not in lap_ids:
        lap_ids.append(ref)
    samples_by_id = await svc(request).repo.get_laps_samples(lap_ids)
    if ref not in samples_by_id:
        raise HTTPException(404, f"reference lap {ref} not found")

    out: dict[str, Any] = {"ref": ref, "step": step, "laps": {}}
    for lap_id, samples in samples_by_id.items():
        entry: dict[str, Any] = {
            "series": analysis.resample_by_distance(samples, step, COMPARE_COLUMNS),
            "peaks_valleys": analysis.speed_peaks_valleys(samples),
        }
        if lap_id != ref:
            entry["delta"] = analysis.time_delta_series(samples, samples_by_id[ref], step)
        out["laps"][str(lap_id)] = entry
    return out


@router.get("/analysis/deviation")
async def deviation(
    request: Request,
    session_id: int,
    count: int = Query(5, ge=2, le=20),
) -> dict[str, Any]:
    """Speed deviation across the session's best `count` laps."""
    lap_rows = await svc(request).repo.list_laps(session_id)
    best = sorted(lap_rows, key=lambda r: r["time_ms"])[:count]
    samples = await svc(request).repo.get_laps_samples([r["id"] for r in best])
    result = analysis.speed_deviation(list(samples.values()))
    result["lap_ids"] = [r["id"] for r in best]
    return result


@router.get("/analysis/fuel")
async def fuel(request: Request, lap_id: int) -> dict[str, Any]:
    """Relative fuel map based on a lap's consumption and time."""
    lap = await svc(request).repo.get_lap(lap_id, with_samples=False)
    if lap is None:
        raise HTTPException(404, "lap not found")
    service = svc(request)
    fuel_level = (
        service.latest_packet.fuel_level if service.latest_packet else lap["fuel_end"]
    )
    rows = analysis.fuel_map(fuel_level, lap["fuel_consumed"], lap["time_ms"])
    return {
        "fuel_level": fuel_level,
        "base_lap_ms": lap["time_ms"],
        "base_fuel_per_lap": lap["fuel_consumed"],
        "rows": [asdict(r) for r in rows],
    }


# --- controls ---------------------------------------------------------------


class RecordingPayload(BaseModel):
    recording: bool


@router.post("/control/recording")
async def set_recording(request: Request, payload: RecordingPayload) -> dict[str, Any]:
    svc(request).recording = payload.recording
    return await svc(request).status()


@router.post("/control/log-lap-now")
async def log_lap_now(request: Request) -> dict[str, Any]:
    result = await svc(request).log_lap_now()
    if result is None:
        raise HTTPException(409, "no lap in progress")
    return result
