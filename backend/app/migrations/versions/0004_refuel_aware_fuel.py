"""Compatibility marker for databases upgraded on the sibling feature branch.

That branch performed a refuel aggregate rewrite backed by metrics-revision
columns that are deliberately outside this rollback branch. Keeping the same
revision identity makes those already-upgraded databases readable; there is
no schema or data change to apply here.

Revision ID: 0004_refuel_aware_fuel
Revises: 0003_fork_telemetry_metrics
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0004_refuel_aware_fuel"
down_revision: str | None = "0003_fork_telemetry_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
