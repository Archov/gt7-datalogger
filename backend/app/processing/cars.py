"""Car ID -> display name lookup.

The bundled data/cars.csv contains a small sample. Run
`python scripts/update_cars.py` to fetch the complete, up-to-date list from
the community-maintained ddm999/gt7info repository.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class CarDatabase:
    def __init__(self) -> None:
        self._names: dict[int, str] = {}

    def load(self, path: Path) -> None:
        if not path.exists():
            log.warning("cars csv not found at %s; car names will show as IDs", path)
            return
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    self._names[int(row["id"])] = row["name"]
                except (KeyError, ValueError):
                    continue
        log.info("loaded %d car names", len(self._names))

    def name(self, car_id: int) -> str:
        return self._names.get(car_id, f"Car #{car_id}")
