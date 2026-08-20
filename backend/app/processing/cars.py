"""Authoritative, database-backed gt-telemetry vehicle catalog."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from app.storage.repository import Repository

log = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = "https://static.zetetos.com/gt7/data"
DEFAULT_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "cars.seed.json"
PoweredAxle = Literal["fwd", "rwd", "awd", "unknown"]


class CarCatalogError(ValueError):
    pass


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CarCatalogError(f"{field} must be a non-empty timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CarCatalogError(f"{field} is not an ISO timestamp") from exc
    return value


def _string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise CarCatalogError(f"{field} must be a string")
    return value


def _integer(data: dict[str, Any], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CarCatalogError(f"{field} must be an integer")
    return value


def _boolean(data: dict[str, Any], field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise CarCatalogError(f"{field} must be a boolean")
    return value


def powered_axle(layout: str | None) -> PoweredAxle:
    """Map authoritative layout codes to the powered axle without inference."""
    if layout == "FF":
        return "fwd"
    if layout in {"FR", "MR", "RR"}:
        return "rwd"
    if layout == "4WD":
        return "awd"
    return "unknown"


def same_timestamp(left: str, right: str) -> bool:
    first = datetime.fromisoformat(left.replace("Z", "+00:00")).replace(microsecond=0)
    second = datetime.fromisoformat(right.replace("Z", "+00:00")).replace(microsecond=0)
    return first == second


@dataclass(frozen=True, slots=True)
class CarDefinition:
    car_id: int
    manufacturer: str
    model: str
    year: int
    open_cockpit: bool
    car_type: str
    category: str
    drivetrain: str
    aspiration: str
    length: int
    width: int
    height: int
    wheelbase: int
    track_front: int
    track_rear: int
    engine_layout: str
    engine_bank_angle: int
    engine_crank_plane_angle: int
    last_modified: str
    raw_json: str

    @classmethod
    def from_source(cls, value: object) -> CarDefinition:
        if not isinstance(value, dict):
            raise CarCatalogError("vehicle definition must be an object")
        data = dict(value)
        car_id = _integer(data, "carId")
        if car_id < 0:
            raise CarCatalogError("carId must be non-negative")
        return cls(
            car_id=car_id,
            manufacturer=_string(data, "manufacturer"),
            model=_string(data, "model"),
            year=_integer(data, "year"),
            open_cockpit=_boolean(data, "openCockpit"),
            car_type=_string(data, "carType"),
            category=_string(data, "category"),
            drivetrain=_string(data, "drivetrain"),
            aspiration=_string(data, "aspiration"),
            length=_integer(data, "length"),
            width=_integer(data, "width"),
            height=_integer(data, "height"),
            wheelbase=_integer(data, "wheelbase"),
            track_front=_integer(data, "trackFront"),
            track_rear=_integer(data, "trackRear"),
            engine_layout=_string(data, "engineLayout"),
            engine_bank_angle=_integer(data, "engineBankAngle"),
            engine_crank_plane_angle=_integer(data, "engineCrankPlaneAngle"),
            last_modified=_timestamp(data.get("lastModified"), "lastModified"),
            raw_json=json.dumps(data, separators=(",", ":"), ensure_ascii=False, sort_keys=True),
        )

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> CarDefinition:
        return cls(**data)

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.manufacturer.strip(), self.model.strip()) if part)

    @property
    def powered_axle(self) -> PoweredAxle:
        return powered_axle(self.drivetrain)

    def storage_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def public_dict(self) -> dict[str, Any]:
        result = self.storage_dict()
        result.pop("raw_json")
        result["display_name"] = self.display_name
        result["powered_axle"] = self.powered_axle
        return result


class CarCatalog:
    """SQLite-backed catalog with an immutable hot-path memory snapshot."""

    def __init__(
        self,
        repo: Repository | None = None,
        *,
        base_url: str = DEFAULT_CATALOG_URL,
        seed_path: Path = DEFAULT_SEED_PATH,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repo = repo
        self.base_url = base_url.rstrip("/")
        self.seed_path = seed_path
        self._transport = transport
        self._cars: dict[int, CarDefinition] = {}
        self._lock = asyncio.Lock()
        self._background_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        if self.repo is None:
            return
        if not await self.repo.list_cars():
            snapshot = json.loads(self.seed_path.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("vehicles"), list):
                raise CarCatalogError("bundled car seed has an invalid envelope")
            definitions = [CarDefinition.from_source(item) for item in snapshot["vehicles"]]
            if len({item.car_id for item in definitions}) != len(definitions):
                raise CarCatalogError("bundled car seed contains duplicate IDs")
            version = _timestamp(snapshot.get("upstreamVersion"), "upstreamVersion")
            if await self.repo.seed_car_catalog(
                [item.storage_dict() for item in definitions], version
            ):
                log.info("seeded %d authoritative car definitions", len(definitions))
        await self.reload()

    async def reload(self) -> None:
        if self.repo is None:
            self._cars = {}
            return
        rows = await self.repo.list_cars()
        self._cars = {int(row["car_id"]): CarDefinition.from_storage(row) for row in rows}

    @property
    def count(self) -> int:
        return len(self._cars)

    def get(self, car_id: int) -> CarDefinition | None:
        return self._cars.get(car_id)

    def all(self) -> list[CarDefinition]:
        return sorted(
            self._cars.values(),
            key=lambda car: (car.manufacturer.casefold(), car.model.casefold(), car.car_id),
        )

    def name(self, car_id: int, fallback: str = "") -> str:
        car = self.get(car_id)
        return car.display_name if car is not None else fallback or f"Car #{car_id}"

    def metadata(self, car_id: int) -> dict[str, Any] | None:
        car = self.get(car_id)
        return car.public_dict() if car is not None else None

    def start_background_refresh(self) -> None:
        if self.repo is None or (self._background_task and not self._background_task.done()):
            return
        self._background_task = asyncio.create_task(self._refresh_in_background())

    async def _refresh_in_background(self) -> None:
        try:
            await self.refresh()
        except CarCatalogError as exc:
            log.warning("car catalog refresh failed; using cached definitions: %s", exc)

    async def stop(self) -> None:
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            await asyncio.gather(self._background_task, return_exceptions=True)
        self._background_task = None

    async def status(self) -> dict[str, Any]:
        state = await self.repo.car_catalog_state() if self.repo is not None else {}
        return {"count": self.count, **state}

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        if self.repo is None:
            raise CarCatalogError("catalog has no repository")
        async with self._lock:
            checked_at = datetime.now(UTC).isoformat()
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=10.0),
                    transport=self._transport,
                ) as client:
                    version_response = await client.get(f"{self.base_url}/version.json")
                    version_response.raise_for_status()
                    version_doc = version_response.json()
                    vehicles_version = _timestamp(
                        (version_doc.get("vehicles") if isinstance(version_doc, dict) else {}).get(
                            "lastModified"
                        ),
                        "vehicles.lastModified",
                    )
                    state = await self.repo.car_catalog_state()
                    local_versions = await self.repo.car_versions()
                    complete = (
                        len(local_versions) > 0
                        and len(local_versions) == int(state.get("expected_count") or 0)
                    )
                    if (
                        not force
                        and complete
                        and state.get("upstream_version") == vehicles_version
                    ):
                        await self.repo.record_car_catalog_check(checked_at)
                        return {
                            "status": "current",
                            "checked": 0,
                            "added": 0,
                            "updated": 0,
                            "removed": 0,
                            "total": self.count,
                            "upstream_version": vehicles_version,
                        }
                    manifest_response = await client.get(
                        f"{self.base_url}/vehicles/manifest.json"
                    )
                    manifest_response.raise_for_status()
                    manifest_doc = manifest_response.json()
                    manifest_raw = (
                        manifest_doc.get("vehicles") if isinstance(manifest_doc, dict) else None
                    )
                    if not isinstance(manifest_raw, dict) or not manifest_raw:
                        raise CarCatalogError("vehicle manifest is empty or invalid")
                    manifest: dict[int, str] = {}
                    for raw_id, entry in manifest_raw.items():
                        if not isinstance(entry, dict):
                            raise CarCatalogError(f"manifest entry {raw_id} must be an object")
                        try:
                            car_id = int(raw_id)
                        except (TypeError, ValueError) as exc:
                            raise CarCatalogError(f"manifest ID {raw_id!r} is invalid") from exc
                        manifest[car_id] = _timestamp(
                            entry.get("lastModified"), f"manifest[{car_id}].lastModified"
                        )
                    changed_ids = sorted(
                        car_id
                        for car_id, modified in manifest.items()
                        if local_versions.get(car_id) != modified
                    )
                    semaphore = asyncio.Semaphore(12)

                    async def download(car_id: int) -> CarDefinition:
                        async with semaphore:
                            response = await client.get(
                                f"{self.base_url}/vehicles/{car_id}.json"
                            )
                            response.raise_for_status()
                            definition = CarDefinition.from_source(response.json())
                            if definition.car_id != car_id:
                                raise CarCatalogError(
                                    f"vehicle {car_id} payload identifies as {definition.car_id}"
                                )
                            if not same_timestamp(definition.last_modified, manifest[car_id]):
                                raise CarCatalogError(
                                    f"vehicle {car_id} timestamp does not match manifest"
                                )
                            # The manifest timestamp is the incremental-sync token. Some
                            # payloads retain sub-second precision, so store the manifest
                            # spelling while raw_json preserves the source document exactly.
                            return replace(definition, last_modified=manifest[car_id])

                    definitions = await asyncio.gather(
                        *(download(car_id) for car_id in changed_ids)
                    )
                counts = await self.repo.apply_car_catalog(
                    [item.storage_dict() for item in definitions],
                    set(manifest),
                    vehicles_version,
                    checked_at,
                )
                await self.reload()
                changed = any(counts[key] for key in ("added", "updated", "removed"))
                result = {
                    "status": "updated" if changed else "current",
                    "checked": len(changed_ids),
                    **counts,
                    "upstream_version": vehicles_version,
                }
                log.info(
                    "car catalog refresh: %d added, %d updated, %d removed (%d total)",
                    counts["added"],
                    counts["updated"],
                    counts["removed"],
                    counts["total"],
                )
                return result
            except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
                message = str(exc) or exc.__class__.__name__
                await self.repo.record_car_catalog_check(checked_at, message)
                raise CarCatalogError(message) from exc
