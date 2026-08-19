"""Fork telemetry archive, hydration, drivetrain, and mirror metadata.

The fork shipped these additive fields before adopting upstream's Alembic
history.  Existing fork databases can therefore already contain any subset
of them, while a fresh upstream-shaped database contains none.  Inspect each
target before adding it so both histories converge safely.

Revision ID: 0003_fork_telemetry_metrics
Revises: 0002_off_survey_count
Create Date: 2026-08-18
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
    session_columns = _columns("sessions")
    if "raw_archive_meta_json" not in session_columns:
        op.add_column(
            "sessions",
            sa.Column(
                "raw_archive_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if "telemetry_hydration_meta_json" not in session_columns:
        op.add_column(
            "sessions",
            sa.Column(
                "telemetry_hydration_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if "metrics_revision" not in session_columns:
        op.add_column(
            "sessions",
            sa.Column("metrics_revision", sa.Integer(), nullable=False, server_default="1"),
        )

    lap_columns = _columns("laps")
    if "telemetry_meta_json" not in lap_columns:
        op.add_column(
            "laps",
            sa.Column(
                "telemetry_meta_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    if "metrics_revision" not in lap_columns:
        op.add_column(
            "laps",
            sa.Column("metrics_revision", sa.Integer(), nullable=False, server_default="1"),
        )

    if "car_drivetrains" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "car_drivetrains",
            sa.Column("car_id", sa.Integer(), nullable=False),
            sa.Column("drivetrain", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("car_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "car_drivetrains" in set(inspector.get_table_names()):
        op.drop_table("car_drivetrains")

    lap_columns = _columns("laps")
    if "metrics_revision" in lap_columns:
        op.drop_column("laps", "metrics_revision")
    if "telemetry_meta_json" in lap_columns:
        op.drop_column("laps", "telemetry_meta_json")

    session_columns = _columns("sessions")
    if "metrics_revision" in session_columns:
        op.drop_column("sessions", "metrics_revision")
    if "telemetry_hydration_meta_json" in session_columns:
        op.drop_column("sessions", "telemetry_hydration_meta_json")
    if "raw_archive_meta_json" in session_columns:
        op.drop_column("sessions", "raw_archive_meta_json")
