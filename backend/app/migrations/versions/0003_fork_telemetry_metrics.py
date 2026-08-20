"""Raw archive and extended telemetry metadata.

The feature branches shipped these columns before Alembic was adopted. The
existence checks let those pre-Alembic databases be stamped at the baseline
and upgraded without trying to add either column twice.

The revision identifier intentionally matches the broader sibling-branch
migration. Databases that visited that branch may contain additional additive
metrics columns; SQLAlchemy safely ignores them, while fresh databases on this
branch receive only the fields modeled here.

Revision ID: 0003_fork_telemetry_metrics
Revises: 0002_off_survey_count
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_fork_telemetry_metrics"
down_revision: str | None = "0002_off_survey_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "raw_archive_meta_json" not in _columns("sessions"):
        op.add_column(
            "sessions",
            sa.Column(
                "raw_archive_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if "telemetry_meta_json" not in _columns("laps"):
        op.add_column(
            "laps",
            sa.Column(
                "telemetry_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )


def downgrade() -> None:
    if "telemetry_meta_json" in _columns("laps"):
        op.drop_column("laps", "telemetry_meta_json")
    if "raw_archive_meta_json" in _columns("sessions"):
        op.drop_column("sessions", "raw_archive_meta_json")
