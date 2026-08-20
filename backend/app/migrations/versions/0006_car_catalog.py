"""Replace user drivetrain overrides with the authoritative vehicle catalog.

Revision ID: 0006_car_catalog
Revises: 0005_hydration_drivetrain
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_car_catalog"
down_revision: str | None = "0005_hydration_drivetrain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "cars" not in tables:
        op.create_table(
            "cars",
            sa.Column("car_id", sa.Integer(), nullable=False),
            sa.Column("manufacturer", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("open_cockpit", sa.Boolean(), nullable=False),
            sa.Column("car_type", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("drivetrain", sa.String(), nullable=False),
            sa.Column("aspiration", sa.String(), nullable=False),
            sa.Column("length", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("wheelbase", sa.Integer(), nullable=False),
            sa.Column("track_front", sa.Integer(), nullable=False),
            sa.Column("track_rear", sa.Integer(), nullable=False),
            sa.Column("engine_layout", sa.String(), nullable=False),
            sa.Column("engine_bank_angle", sa.Integer(), nullable=False),
            sa.Column("engine_crank_plane_angle", sa.Integer(), nullable=False),
            sa.Column("last_modified", sa.String(), nullable=False),
            sa.Column("raw_json", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("car_id"),
        )
    if "car_catalog_state" not in tables:
        op.create_table(
            "car_catalog_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("upstream_version", sa.String(), nullable=False, server_default=""),
            sa.Column("expected_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_checked_at", sa.String(), nullable=False, server_default=""),
            sa.Column("last_success_at", sa.String(), nullable=False, server_default=""),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
        )
    if "car_drivetrains" in tables:
        op.drop_table("car_drivetrains")


def downgrade() -> None:
    tables = _tables()
    if "car_drivetrains" not in tables:
        op.create_table(
            "car_drivetrains",
            sa.Column("car_id", sa.Integer(), nullable=False),
            sa.Column("drivetrain", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("car_id"),
        )
    if "car_catalog_state" in tables:
        op.drop_table("car_catalog_state")
    if "cars" in tables:
        op.drop_table("cars")
