"""Database engine + ORM models. SQLite by default; any SQLAlchemy async URL works."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[str]
    car_id: Mapped[int]
    car_name: Mapped[str]
    note: Mapped[str] = mapped_column(default="")

    laps: Mapped[list[LapRow]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SettingRow(Base):
    """Runtime-configurable settings (override env defaults at startup)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]


class LapRow(Base):
    __tablename__ = "laps"
    __table_args__ = (Index("ix_laps_session", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    number: Mapped[int]
    time_ms: Mapped[int]
    finished_at: Mapped[str]
    car_id: Mapped[int]
    fuel_start: Mapped[float]
    fuel_end: Mapped[float]
    fuel_consumed: Mapped[float]
    full_throttle_pct: Mapped[float]
    full_brake_pct: Mapped[float]
    coasting_pct: Mapped[float]
    tire_spin_pct: Mapped[float]
    max_speed: Mapped[float]
    min_body_height: Mapped[float]
    total_ticks: Mapped[int]
    samples_json: Mapped[str] = mapped_column(Text)

    session: Mapped[SessionRow] = relationship(back_populates="laps")


def make_engine(db_path: Path | str) -> AsyncEngine:
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{db_path}"
    else:
        url = db_path  # full SQLAlchemy URL (e.g. postgresql+asyncpg://...)
    return create_async_engine(url)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
