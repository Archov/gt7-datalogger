"""Add archive hydration metadata and per-car drivetrain overrides.

The checks make this safe for databases that previously visited llm-export,
where both additions may already exist despite an older Alembic revision.

Revision ID: 0005_hydration_drivetrain
Revises: 0004_refuel_aware_fuel
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_hydration_drivetrain"
down_revision: str | None = "0004_refuel_aware_fuel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "telemetry_hydration_meta_json" not in _columns("sessions"):
        op.add_column(
            "sessions",
            sa.Column(
                "telemetry_hydration_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if "car_drivetrains" not in _tables():
        op.create_table(
            "car_drivetrains",
            sa.Column("car_id", sa.Integer(), nullable=False),
            sa.Column("drivetrain", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("car_id"),
        )


def downgrade() -> None:
    if "car_drivetrains" in _tables():
        op.drop_table("car_drivetrains")
    if "telemetry_hydration_meta_json" in _columns("sessions"):
        op.drop_column("sessions", "telemetry_hydration_meta_json")
