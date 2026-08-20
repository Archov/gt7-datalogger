"""Authoritative gt-telemetry car catalog."""

from __future__ import annotations

import json

import httpx
import pytest

from app.processing.cars import CarCatalog, CarCatalogError, CarDefinition, powered_axle
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository


def vehicle(car_id: int, *, modified: str = "2026-01-01T00:00:00Z", **extra):
    return {
        "carId": car_id,
        "manufacturer": "Mazda",
        "model": "Roadster '15",
        "year": 2015,
        "openCockpit": True,
        "carType": "street",
        "category": "Gr.N",
        "drivetrain": "FR",
        "aspiration": "NA",
        "length": 3915,
        "width": 1735,
        "height": 1235,
        "wheelbase": 2310,
        "trackFront": 1495,
        "trackRear": 1505,
        "engineLayout": "I4",
        "engineBankAngle": 0,
        "engineCrankPlaneAngle": 180,
        "lastModified": modified,
        **extra,
    }


@pytest.fixture
async def catalog_repo(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    yield repo
    await engine.dispose()


def test_definition_preserves_all_known_and_future_fields() -> None:
    definition = CarDefinition.from_source(vehicle(7, futureField={"kept": True}))
    assert definition.display_name == "Mazda Roadster '15"
    assert definition.powered_axle == "rwd"
    assert definition.open_cockpit is True
    assert json.loads(definition.raw_json)["futureField"] == {"kept": True}
    assert {
        "FF": "fwd",
        "FR": "rwd",
        "MR": "rwd",
        "RR": "rwd",
        "4WD": "awd",
        "unknown": "unknown",
    } == {layout: powered_axle(layout) for layout in ("FF", "FR", "MR", "RR", "4WD", "unknown")}


async def test_empty_database_bootstraps_from_bundled_shape(catalog_repo, tmp_path) -> None:
    seed = tmp_path / "cars.seed.json"
    seed.write_text(
        json.dumps(
            {
                "source": "test",
                "upstreamVersion": "2026-01-01T00:00:00Z",
                "vehicles": [vehicle(7, futureField="preserved")],
            }
        ),
        encoding="utf-8",
    )
    catalog = CarCatalog(catalog_repo, seed_path=seed)
    await catalog.initialize()
    await catalog.initialize()
    assert catalog.count == 1
    assert catalog.name(7) == "Mazda Roadster '15"
    rows = await catalog_repo.list_cars()
    assert len(rows) == 1
    assert json.loads(rows[0]["raw_json"])["futureField"] == "preserved"


async def test_manifest_refresh_adds_updates_and_removes_atomically(catalog_repo, tmp_path) -> None:
    seed = tmp_path / "cars.seed.json"
    seed.write_text(
        json.dumps(
            {
                "upstreamVersion": "2026-01-01T00:00:00Z",
                "vehicles": [vehicle(1), vehicle(9)],
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/version.json"):
            return httpx.Response(
                200, json={"vehicles": {"lastModified": "2026-02-01T00:00:00Z"}}
            )
        if path.endswith("/vehicles/manifest.json"):
            return httpx.Response(
                200,
                json={
                    "vehicles": {
                        "1": {"lastModified": "2026-02-01T00:00:00Z"},
                        "2": {"lastModified": "2026-02-01T00:00:00Z"},
                    }
                },
            )
        car_id = int(path.rsplit("/", 1)[1].removesuffix(".json"))
        return httpx.Response(
            200,
            json=vehicle(
                car_id,
                modified="2026-02-01T00:00:00.500000Z",
                model=f"Model {car_id}",
            ),
        )

    catalog = CarCatalog(
        catalog_repo,
        base_url="https://catalog.test/data",
        seed_path=seed,
        transport=httpx.MockTransport(handler),
    )
    await catalog.initialize()
    result = await catalog.refresh()
    assert result == {
        "status": "updated",
        "checked": 2,
        "added": 1,
        "updated": 1,
        "removed": 1,
        "total": 2,
        "upstream_version": "2026-02-01T00:00:00Z",
    }
    assert [car.car_id for car in catalog.all()] == [1, 2]
    assert catalog.name(2) == "Mazda Model 2"


async def test_invalid_refresh_keeps_previous_catalog(catalog_repo, tmp_path) -> None:
    seed = tmp_path / "cars.seed.json"
    seed.write_text(
        json.dumps(
            {
                "upstreamVersion": "2026-01-01T00:00:00Z",
                "vehicles": [vehicle(1)],
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/version.json"):
            return httpx.Response(
                200, json={"vehicles": {"lastModified": "2026-02-01T00:00:00Z"}}
            )
        if request.url.path.endswith("/manifest.json"):
            return httpx.Response(
                200,
                json={"vehicles": {"2": {"lastModified": "2026-02-01T00:00:00Z"}}},
            )
        return httpx.Response(200, json={"carId": 999})

    catalog = CarCatalog(
        catalog_repo,
        base_url="https://catalog.test/data",
        seed_path=seed,
        transport=httpx.MockTransport(handler),
    )
    await catalog.initialize()
    with pytest.raises(CarCatalogError):
        await catalog.refresh()
    assert catalog.name(1) == "Mazda Roadster '15"
    assert await catalog_repo.car_versions() == {1: "2026-01-01T00:00:00Z"}
    assert (await catalog.status())["last_error"]
