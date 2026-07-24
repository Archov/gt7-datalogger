"""Fetch the complete GT7 car ID -> name list from ddm999/gt7info.

Usage: python scripts/update_cars.py [output_path]
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/ddm999/gt7info/web-new/_data/db/cars.csv"


def main() -> None:
    default = Path(__file__).parent.parent / "data" / "cars.csv"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    print(f"downloading {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    # Upstream columns: ID, ShortName, Maker (header names may vary in case).
    reader = csv.DictReader(io.StringIO(raw))
    fields = {f.lower(): f for f in reader.fieldnames or []}
    id_col = fields.get("id")
    name_col = fields.get("shortname") or fields.get("name")
    if not id_col or not name_col:
        sys.exit(f"unexpected columns in upstream csv: {reader.fieldnames}")

    rows = [(row[id_col], row[name_col]) for row in reader if row.get(id_col)]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} cars to {out}")


if __name__ == "__main__":
    main()
