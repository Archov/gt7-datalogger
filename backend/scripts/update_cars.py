"""Generate the bundled authoritative car snapshot from gt-telemetry JSON.

Usage: python scripts/update_cars.py [output_path]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.processing.cars import DEFAULT_CATALOG_URL, CarDefinition, same_timestamp


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "gt7-datalogger/0.5"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).parent.parent / "app" / "data" / "cars.seed.json"
    )
    version_doc = _get_json(f"{DEFAULT_CATALOG_URL}/version.json")
    upstream_version = version_doc["vehicles"]["lastModified"]
    manifest_doc = _get_json(f"{DEFAULT_CATALOG_URL}/vehicles/manifest.json")
    manifest = manifest_doc["vehicles"]
    ids = sorted(int(raw_id) for raw_id in manifest)

    def fetch(car_id: int) -> dict[str, Any]:
        raw = _get_json(f"{DEFAULT_CATALOG_URL}/vehicles/{car_id}.json")
        definition = CarDefinition.from_source(raw)
        if definition.car_id != car_id:
            raise ValueError(f"vehicle {car_id} payload identifies as {definition.car_id}")
        manifest_modified = manifest[str(car_id)]["lastModified"]
        if not same_timestamp(definition.last_modified, manifest_modified):
            raise ValueError(f"vehicle {car_id} timestamp does not match manifest")
        definition = replace(definition, last_modified=manifest_modified)
        return json.loads(definition.raw_json)

    with ThreadPoolExecutor(max_workers=12) as pool:
        vehicles = list(pool.map(fetch, ids))
    document = {
        "source": DEFAULT_CATALOG_URL,
        "upstreamVersion": upstream_version,
        "vehicles": vehicles,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(vehicles)} authoritative car definitions to {output}")


if __name__ == "__main__":
    main()
