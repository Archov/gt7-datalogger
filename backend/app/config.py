"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GT7_", env_file=".env", extra="ignore")

    # "udp" captures from a PlayStation, "sim" replays bundled sample data.
    source: str = "udp"
    ps_ip: str = ""  # empty -> broadcast auto-discovery
    heartbeat_port: int = 33739
    telemetry_port: int = 33740

    db_path: Path = Path("data/gt7.db")
    cars_csv: Path = Path("data/cars.csv")
    sample_lap: Path = Path("data/sample_lap.json")

    http_host: str = "0.0.0.0"
    http_port: int = 8000

    # Client stream rate (Hz). Raw capture is ~60 Hz; the UI does not need all of it.
    ws_rate: int = 30

    log_level: str = "INFO"

    # Webhook for personal-best / session-summary notifications
    # (Discord webhook URLs get a rich embed; other URLs get plain JSON).
    webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
