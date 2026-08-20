"""Regenerate the checked-in protocol catalog from the declarative registry."""

from __future__ import annotations

import json
from pathlib import Path

from app.telemetry.packet_catalog import catalog_document, validate_packet_catalog


def main() -> None:
    validate_packet_catalog()
    target = Path(__file__).parents[2] / "docs" / "reference" / "packet-field-catalog.json"
    target.write_text(
        json.dumps(catalog_document(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
